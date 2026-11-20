using System.Diagnostics;
using System.Text;

namespace OpenGeul.Office.Core;

public static class WorkerLaunch
{
    public static ProcessStartInfo Create(string packageRoot)
    {
        var runtime = Path.Combine(packageRoot, "Office");
        var program = Path.Combine(runtime, "program");
        var core = SelectCore(program);
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
    private static string SelectCore(string program)
    {
        try
        {
            var loader = ReadMetadata(Path.Combine(program, "pythonloader.uno.ini"), 1024);
            var version = loader == Loader("3.13.15") ? "3.13.15"
                : loader == Loader("3.13.17") ? "3.13.17" : throw new InvalidDataException();
            var expectedBuild = version == "3.13.15"
                ? "bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1"
                : "9dea406ab7695df6325b11b0e19fdca8db4b7276";
            var lines = ReadMetadata(Path.Combine(program, "version.ini"), 8192).Split('\n');
            if (lines[0] != "[Version]") throw new InvalidDataException();
            var fields = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var line in lines.Skip(1).Where(line => line.Length != 0))
            {
                var separator = line.IndexOf('=');
                if (separator <= 0) throw new InvalidDataException();
                var key = line[..separator];
                if (key != key.Trim() || !fields.TryAdd(key, line[(separator + 1)..])) throw new InvalidDataException();
            }
            if (!fields.TryGetValue("buildid", out var build) || build != expectedBuild) throw new InvalidDataException();
            var core = Path.Combine(program, "python-core-" + version);
            var other = Path.Combine(program, "python-core-" + (version == "3.13.15" ? "3.13.17" : "3.13.15"));
            if (Directory.Exists(other) || File.Exists(other)) throw new InvalidDataException();
            foreach (var folder in new[] { core, Path.Combine(core, "bin"), Path.Combine(core, "lib"), Path.Combine(core, "lib", "encodings") })
                RequirePlain(folder, directory: true);
            RequirePlain(Path.Combine(core, "bin", "python.exe"), directory: false);
            RequirePlain(Path.Combine(core, "lib", "encodings", "__init__.py"), directory: false);
            return core;
        }
        catch (Exception error) when (error is IOException or InvalidDataException or UnauthorizedAccessException or DecoderFallbackException)
        {
            throw new SuiteException("Office 문서 작업자의 Python 런타임 구성을 확인할 수 없습니다.");
        }
    }

    private static string Loader(string version) => "[Bootstrap]\nPYUNO_LOADER_PYTHONHOME=$ORIGIN/python-core-" + version
        + "\nPYUNO_LOADER_PYTHONPATH=$ORIGIN/python-core-" + version + "/lib $ORIGIN/python-core-" + version + "/lib/site-packages $ORIGIN\n";

    private static void RequirePlain(string path, bool directory)
    {
        var attributes = File.GetAttributes(path);
        if ((attributes & FileAttributes.ReparsePoint) != 0 || ((attributes & FileAttributes.Directory) != 0) != directory)
            throw new InvalidDataException();
    }

    private static string ReadMetadata(string path, int maximum)
    {
        RequirePlain(path, directory: false);
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length <= 0 || stream.Length > maximum) throw new InvalidDataException();
        var buffer = new byte[maximum + 1];
        var length = 0;
        while (length < buffer.Length)
        {
            var count = stream.Read(buffer, length, buffer.Length - length);
            if (count == 0) break;
            length += count;
        }
        if (length == 0 || length > maximum) throw new InvalidDataException();
        return new UTF8Encoding(false, true).GetString(buffer, 0, length).Replace("\r\n", "\n", StringComparison.Ordinal);
    }

}
