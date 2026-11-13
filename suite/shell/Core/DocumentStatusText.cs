namespace OpenGeul.Office.Core;

public static class DocumentStatusText
{
    public static string Format(string moduleId, bool modified, bool hasPath, string? readinessMessage)
    {
        if (moduleId != "base")
            return modified ? "변경 내용이 있습니다." : hasPath ? "준비 · 저장됨" : "준비 · 새 문서";
        var status = modified ? "변경 내용이 있습니다." : hasPath ? "저장됨" : "새 문서";
        var readiness = string.IsNullOrWhiteSpace(readinessMessage)
            ? "데이터베이스 연결과 추가 구성 요소의 준비 상태가 확인되지 않았습니다."
            : readinessMessage;
        return $"{status} · {readiness}";
    }
}
