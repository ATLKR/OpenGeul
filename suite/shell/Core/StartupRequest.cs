namespace OpenGeul.Office.Core;

public sealed record StartupRequest(string? ModuleId, string? Path)
{
    public static StartupRequest Parse(string[] args, SuiteManifest manifest)
    {
        string? module = null, path = null;
        for (var i = 0; i < args.Length; i++)
        {
            if (args[i] == "--module" && module is null && i + 1 < args.Length) module = args[++i];
            else if (args[i] == "--file" && path is null && i + 1 < args.Length) path = LocalDocumentPath.Validate(args[++i]);
            else if (args.Length == 1 && !args[i].StartsWith("--", StringComparison.Ordinal)) path = LocalDocumentPath.Validate(args[i]);
            else throw new SuiteException("시작 옵션이 올바르지 않습니다. --module 모듈명 또는 --file 전체경로를 사용해 주세요.");
        }
        if (module is not null && !manifest.Modules.ContainsKey(module)) throw new SuiteException("지원하지 않는 모듈입니다.");
        if (path is not null)
        {
            var routed = manifest.Route(path).Id;
            if (module is not null && module != routed) throw new SuiteException("선택한 모듈과 파일 형식이 일치하지 않습니다.");
            module = routed;
        }
        return new(module, path);
    }
}
