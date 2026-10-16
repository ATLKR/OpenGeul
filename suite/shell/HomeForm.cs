using System.Diagnostics;
using OpenGeul.Office.Core;

namespace OpenGeul.Office;

internal sealed class HomeForm : Form
{
    private readonly string packageRoot;
    private readonly SuiteManifest manifest;
    private readonly List<OfficeDocumentForm> documents = [];
    private bool closing;
    private bool closeApproved;

    public HomeForm(string packageRoot, SuiteManifest manifest, StartupRequest startup)
    {
        this.packageRoot = packageRoot;
        this.manifest = manifest;
        Text = manifest.ProductName;
        SuiteWindowIcon.Apply(this);
        Name = "OpenGeulOfficeHome";
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96F, 96F);
        MinimumSize = new Size(850, 700);
        ClientSize = new Size(1050, 800);
        BackColor = Color.FromArgb(246, 245, 241);
        ForeColor = Color.FromArgb(28, 49, 61);

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 4, Padding = new Padding(32) };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 108));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 65));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        var heading = new Panel { Dock = DockStyle.Fill };
        heading.Controls.Add(new Label { Text = "OpenGeul Office", AutoSize = true, Font = new Font(Font.FontFamily, 27F, FontStyle.Bold), Location = new Point(0, 0) });
        heading.Controls.Add(new Label { Text = "생각을 문서로, 데이터를 한눈에.", AutoSize = true, Location = new Point(3, 62), ForeColor = Color.FromArgb(91, 107, 113) });
        layout.Controls.Add(heading, 0, 0);

        var actions = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight };
        var open = new Button { Text = "파일 열기…", AutoSize = false, Size = new Size(170, 43), BackColor = Color.FromArgb(28, 64, 78), ForeColor = Color.White, FlatStyle = FlatStyle.Flat, Cursor = Cursors.Hand };
        open.FlatAppearance.BorderSize = 0;
        open.Click += (_, _) => OpenFile();
        actions.Controls.Add(open);
        actions.Controls.Add(new Label { Text = "새 문서를 만들려면 아래 앱을 선택하세요.", AutoSize = true, Margin = new Padding(18, 11, 0, 0), ForeColor = Color.FromArgb(91, 107, 113) });
        layout.Controls.Add(actions, 0, 1);

        var grid = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 3 };
        for (var i = 0; i < 3; i++)
        {
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F / 3));
            grid.RowStyles.Add(new RowStyle(SizeType.Percent, 100F / 3));
        }
        var descriptions = new Dictionary<string, (string Letter, string Description, Color Color)>
        {
            ["hwp"] = ("한", "한글 문서 · HWP / HWPX", Color.FromArgb(20, 128, 128)),
            ["writer"] = ("W", "글과 문서 · DOCX / ODT", Color.FromArgb(43, 105, 177)),
            ["calc"] = ("C", "표와 데이터 · XLSX / ODS", Color.FromArgb(48, 132, 86)),
            ["impress"] = ("I", "발표 자료 · PPTX / ODP", Color.FromArgb(203, 101, 52)),
            ["draw"] = ("D", "그림과 도형 · ODG", Color.FromArgb(166, 130, 34)),
            ["math"] = ("M", "수식과 기호 · ODF", Color.FromArgb(126, 87, 165)),
            ["base"] = ("B", "데이터베이스 · ODB", Color.FromArgb(91, 111, 131))
        };
        for (var i = 0; i < SuiteManifest.ModuleOrder.Count; i++)
        {
            var id = SuiteManifest.ModuleOrder[i];
            var module = manifest.Modules[id];
            var visual = descriptions[id];
            var tile = new OfficeTile(module.DisplayName, visual.Letter, visual.Description, visual.Color) { Dock = DockStyle.Fill, Margin = new Padding(0, 0, 14, 14), AccessibleName = module.DisplayName };
            tile.Click += (_, _) => OpenModule(id);
            grid.Controls.Add(tile, i % 3, i / 3);
        }
        layout.Controls.Add(grid, 0, 2);
        layout.Controls.Add(new Label { Text = "문서 · 스프레드시트 · 프레젠테이션, 한곳에서 시작하세요.", Dock = DockStyle.Fill, TextAlign = ContentAlignment.BottomLeft, ForeColor = Color.FromArgb(108, 119, 122), Font = new Font(Font.FontFamily, 9F) }, 0, 3);
        Controls.Add(layout);
        FormClosing += OnHomeClosing;
        Shown += (_, _) => { if (startup.ModuleId is not null) OpenModule(startup.ModuleId, startup.Path); };
    }

    internal void OpenFile()
    {
        if (closing) return;
        using var dialog = new OpenFileDialog { Title = "OpenGeul Office에서 문서 열기", Filter = manifest.OpenDialogFilter, CheckFileExists = true, Multiselect = false };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try { OpenModule(manifest.Route(dialog.FileName).Id, dialog.FileName); }
        catch (Exception e) { Program.ShowError(e.Message, this); }
    }

    internal void OpenModule(string id, string? path = null)
    {
        if (closing) return;
        try
        {
            if (!manifest.Modules.TryGetValue(id, out var module)) throw new SuiteException("지원하지 않는 모듈입니다.");
            if (path is not null)
            {
                if (manifest.Route(path).Id != id) throw new SuiteException("선택한 모듈과 파일 형식이 일치하지 않습니다.");
                if (!File.Exists(path)) throw new SuiteException("선택한 문서가 없습니다. 파일 위치를 확인해 주세요.");
            }
            if (module.IsHwp)
            {
                var executable = Path.Combine(packageRoot, "HWP", "OpenGeul.exe");
                if (!File.Exists(executable)) throw new SuiteException("HWP 구성 요소가 이 패키지에 포함되어 있지 않습니다. 검증된 OpenGeul HWP 구성 요소를 포함한 패키지를 사용해 주세요.");
                using var launched = Process.Start(HwpLaunch.Create(packageRoot, path)) ?? throw new SuiteException("OpenGeul HWP를 시작할 수 없습니다.");
                return;
            }
            if (!File.Exists(Path.Combine(packageRoot, "Office", "program", "python.exe")) || !File.Exists(Path.Combine(packageRoot, "Office", "program", "soffice.exe")) || !File.Exists(Path.Combine(packageRoot, "worker", "office_worker.py")))
                throw new SuiteException("Office 런타임 또는 문서 작업자가 없습니다. 완전한 OpenGeul Office 패키지를 사용해 주세요.");
            var form = new OfficeDocumentForm(packageRoot, module, path, OpenFile, requested => OpenModule(requested));
            documents.Add(form);
            form.FormClosed += (_, _) => documents.Remove(form);
            // Home performs the asynchronous close sequence explicitly. A WinForms owner
            // would synchronously close its owned forms before that sequence can finish.
            form.Show();
        }
        catch (Exception e) { Program.ShowError(e is SuiteException ? e.Message : "문서를 열 수 없습니다.\n" + e.Message, this); }
    }

    private async void OnHomeClosing(object? sender, FormClosingEventArgs e)
    {
        if (closeApproved) return;
        e.Cancel = true;
        if (closing) return;
        closing = true;
        try
        {
            foreach (var document in documents.ToArray())
                if (!await document.RequestCloseAsync()) return;
            closeApproved = true;
            Close();
        }
        finally { closing = false; }
    }
}

internal sealed class OfficeTile(string title, string letter, string description, Color accent) : Button
{
    private bool hover;

    protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { hover = false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnPaint(PaintEventArgs e)
    {
        var scale = DeviceDpi / 96F;
        int Px(int value) => (int)Math.Round(value * scale);
        e.Graphics.Clear(hover ? Color.FromArgb(251, 253, 253) : Color.White);
        using var border = new Pen(Focused || hover ? accent : Color.FromArgb(225, 229, 227), Px(Focused ? 2 : 1));
        e.Graphics.DrawRectangle(border, 0, 0, Width - 1, Height - 1);
        using var brush = new SolidBrush(accent);
        e.Graphics.FillRectangle(brush, Px(20), Px(20), Px(38), Px(38));
        using var letterFont = new Font(Font.FontFamily, 16F, FontStyle.Bold);
        TextRenderer.DrawText(e.Graphics, letter, letterFont, new Rectangle(Px(20), Px(20), Px(38), Px(38)), Color.White, TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        using var titleFont = new Font(Font.FontFamily, 12F, FontStyle.Bold);
        TextRenderer.DrawText(e.Graphics, title, titleFont, new Rectangle(Px(71), Px(27), Width - Px(85), Px(30)), Color.FromArgb(28, 49, 61), TextFormatFlags.EndEllipsis | TextFormatFlags.SingleLine);
        TextRenderer.DrawText(e.Graphics, description, Font, new Rectangle(Px(20), Px(77), Width - Px(35), Px(28)), Color.FromArgb(91, 107, 113), TextFormatFlags.EndEllipsis | TextFormatFlags.SingleLine);
    }
}
