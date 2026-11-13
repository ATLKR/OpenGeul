using OpenGeul.Office.Core;

namespace OpenGeul.Office;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        Application.SetDefaultFont(new Font("Malgun Gothic", 10F));
        Application.ThreadException += (_, e) => ShowError("예기치 않은 오류가 발생했습니다. 열려 있는 문서를 확인해 주세요.\n" + e.Exception.Message);
        try
        {
            var packageRoot = AppContext.BaseDirectory;
            var manifestPath = Path.Combine(packageRoot, "suite-product.json");
            if (!File.Exists(manifestPath)) throw new SuiteException("제품 설정 파일(suite-product.json)이 없습니다. OpenGeul Office 패키지를 다시 확인해 주세요.");
            var manifest = SuiteManifest.Parse(File.ReadAllText(manifestPath));
            var startup = StartupRequest.Parse(args, manifest);
            Application.Run(new HomeForm(packageRoot, manifest, startup));
        }
        catch (Exception e) { ShowError(e is SuiteException ? e.Message : "OpenGeul Office를 시작할 수 없습니다.\n" + e.Message); }
    }

    internal static void ShowError(string message, IWin32Window? owner = null) =>
        MessageBox.Show(owner, message, "OpenGeul Office", MessageBoxButtons.OK, MessageBoxIcon.Error);
}
