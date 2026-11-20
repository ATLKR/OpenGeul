using System.Collections.ObjectModel;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace OpenGeul.Office.Core;

public sealed class SuiteModule(string id, string displayName, string? factory, IReadOnlyList<string> extensions, IReadOnlyDictionary<string, string> filters)
{
    public string Id { get; } = id;
    public string DisplayName { get; } = displayName;
    public string? Factory { get; } = factory;
    public IReadOnlyList<string> Extensions { get; } = extensions;
    public IReadOnlyDictionary<string, string> Filters { get; } = filters;
    public bool IsHwp => Id == "hwp";
    public string DefaultExtension => Extensions[0];
    public string DialogFilter => string.Join("|", Extensions.Select(ext => $"{DisplayName} (*.{ext})|*.{ext}"));

    public string SaveFilter(string path)
    {
        LocalDocumentPath.Validate(path);
        var extension = Path.GetExtension(path).TrimStart('.');
        if (!Filters.TryGetValue(extension, out var filter))
            throw new SuiteException($"{DisplayName}에서 저장할 수 없는 파일 형식입니다: {extension}");
        return filter;
    }
}

public sealed class SuiteManifest
{
    public static readonly IReadOnlyList<string> ModuleOrder = Array.AsReadOnly(new[] { "hwp", "writer", "calc", "impress", "draw", "math", "base" });
    public string ProductName { get; } = "OpenGeul Office";
    public IReadOnlyDictionary<string, SuiteModule> Modules { get; }
    private readonly Dictionary<string, SuiteModule> byExtension;

    private SuiteManifest(Dictionary<string, SuiteModule> modules, Dictionary<string, SuiteModule> extensions)
    {
        Modules = new ReadOnlyDictionary<string, SuiteModule>(modules);
        byExtension = extensions;
    }

    public static SuiteManifest Parse(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.GetProperty("schemaVersion").GetInt32() != 1 || root.GetProperty("productName").GetString() != "OpenGeul Office")
                throw new SuiteException("지원하지 않는 OpenGeul Office 제품 설정입니다.");
            var runtime = root.GetProperty("runtime");
            if (runtime.GetProperty("directory").GetString() != "Office" || runtime.GetProperty("executable").GetString() != "program/soffice.exe" || runtime.GetProperty("python").GetString() != "program/python.exe")
                throw new SuiteException("Office 런타임 경로 설정이 올바르지 않습니다.");
            var modulesJson = root.GetProperty("modules");
            if (modulesJson.EnumerateObject().Count() != ModuleOrder.Count)
                throw new SuiteException("제품 구성에 필요한 모듈이 누락되었거나 중복되었습니다.");
            var modules = new Dictionary<string, SuiteModule>(StringComparer.Ordinal);
            var extensions = new Dictionary<string, SuiteModule>(StringComparer.OrdinalIgnoreCase);
            foreach (var id in ModuleOrder)
            {
                var item = modulesJson.GetProperty(id);
                var displayName = item.GetProperty("displayName").GetString();
                if (string.IsNullOrWhiteSpace(displayName) || !displayName.StartsWith("OpenGeul ", StringComparison.Ordinal))
                    throw new SuiteException("모듈 표시 이름이 올바르지 않습니다.");
                var factory = item.GetProperty("factory").GetString();
                var expectedFactory = id == "hwp" ? null : "private:factory/" + (id switch { "writer" => "swriter", "calc" => "scalc", "impress" => "simpress", "draw" => "sdraw", "math" => "smath", "base" => "sdatabase", _ => "" });
                if (factory != expectedFactory || (id == "hwp" && item.GetProperty("executable").GetString() != "HWP/OpenGeul.exe"))
                    throw new SuiteException("모듈 실행 설정이 올바르지 않습니다.");
                var extList = item.GetProperty("extensions").EnumerateArray().Select(e => e.GetString() ?? "").ToArray();
                if (extList.Length == 0 || extList.Any(e => !Regex.IsMatch(e, "^[a-z0-9]+$")) || extList.Distinct(StringComparer.OrdinalIgnoreCase).Count() != extList.Length)
                    throw new SuiteException("모듈 확장자 설정이 올바르지 않습니다.");
                var filters = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                foreach (var filter in item.GetProperty("filters").EnumerateObject())
                {
                    var value = filter.Value.GetString();
                    if (!extList.Contains(filter.Name, StringComparer.OrdinalIgnoreCase) || string.IsNullOrWhiteSpace(value) || !filters.TryAdd(filter.Name, value))
                        throw new SuiteException("저장 필터 설정이 올바르지 않습니다.");
                }
                if ((id == "hwp" && filters.Count != 0) || (id != "hwp" && filters.Count != extList.Length))
                    throw new SuiteException("저장 필터가 누락되었습니다.");
                var module = new SuiteModule(id, displayName, factory, Array.AsReadOnly(extList), new ReadOnlyDictionary<string, string>(filters));
                modules.Add(id, module);
                foreach (var ext in extList)
                    if (!extensions.TryAdd(ext, module)) throw new SuiteException($"여러 모듈에 같은 확장자가 지정되었습니다: {ext}");
            }
            return new SuiteManifest(modules, extensions);
        }
        catch (SuiteException) { throw; }
        catch (Exception e) when (e is JsonException or InvalidOperationException or KeyNotFoundException or ArgumentException)
        {
            throw new SuiteException("OpenGeul Office 제품 설정 파일을 읽을 수 없습니다.", e);
        }
    }

    public SuiteModule Route(string path)
    {
        LocalDocumentPath.Validate(path);
        if (byExtension.TryGetValue(Path.GetExtension(path).TrimStart('.'), out var module)) return module;
        throw new SuiteException("지원하지 않는 파일 형식입니다. HWP, Writer, Calc, Impress, Draw, Math 또는 Base 문서를 선택해 주세요.");
    }

    public string OpenDialogFilter => $"지원하는 문서|{string.Join(";", byExtension.Keys.Select(e => "*." + e))}|모든 파일|*.*";
}

public static class LocalDocumentPath
{
    public static string Validate(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || path.Contains('\0') || path.StartsWith("\\\\", StringComparison.Ordinal) || path.StartsWith("//", StringComparison.Ordinal))
            throw new SuiteException("이 컴퓨터에 저장된 문서의 전체 경로를 선택해 주세요.");
        var windowsAbsolute = Regex.IsMatch(path, "^[A-Za-z]:[\\\\/]");
        var nativeAbsolute = !OperatingSystem.IsWindows() && Path.IsPathFullyQualified(path);
        if ((!windowsAbsolute && !nativeAbsolute) || path.AsSpan(windowsAbsolute ? 2 : 0).Contains(':'))
            throw new SuiteException("웹 주소, 네트워크 경로 또는 상대 경로는 열 수 없습니다. 이 컴퓨터의 문서를 선택해 주세요.");
        return path;
    }
}
