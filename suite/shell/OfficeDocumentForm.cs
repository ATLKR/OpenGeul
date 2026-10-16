using System.Runtime.InteropServices;
using System.Text.Json;
using OpenGeul.Office.Core;

namespace OpenGeul.Office;

internal sealed class OfficeDocumentForm : Form, IDocumentSession
{
    private readonly string packageRoot;
    private readonly SuiteModule module;
    private readonly Action open;
    private readonly Action<string> create;
    private readonly Panel editorPanel = new() { Dock = DockStyle.Fill, BackColor = Color.White, Name = "OfficeHostPanel", TabStop = true };
    private readonly ToolStripStatusLabel statusLabel = new() { Spring = true, TextAlign = ContentAlignment.MiddleLeft, Name = "OfficeDocumentStatus" };
    private readonly ToolStripMenuItem saveMenu = new("저장", null, null, Keys.Control | Keys.S);
    private readonly ToolStripMenuItem saveAsMenu = new("다른 이름으로 저장…", null, null, Keys.Control | Keys.Shift | Keys.S);
    private readonly System.Windows.Forms.Timer resizeTimer = new() { Interval = 100 };
    private readonly System.Windows.Forms.Timer statusTimer = new() { Interval = 1500 };
    private WorkerClient? worker;
    private string? path;
    private bool attached;
    private bool loading;
    private bool busy;
    private bool closing;
    private bool closeApproved;
    private bool resizeBusy;
    private bool statusBusy;
    private Size sentSize;

    internal OfficeDocumentForm(string packageRoot, SuiteModule module, string? path, Action open, Action<string> create)
    {
        this.packageRoot = packageRoot;
        this.module = module;
        this.path = path;
        this.open = open;
        this.create = create;
        Text = $"{(path is null ? "새 문서" : Path.GetFileName(path))} — {module.DisplayName}";
        Name = "OpenGeulOfficeDocument";
        SuiteWindowIcon.Apply(this);
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96F, 96F);
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(1250, 850);
        MinimumSize = new Size(700, 500);
        var menu = new MenuStrip();
        var file = new ToolStripMenuItem("파일");
        file.DropDownItems.Add(new ToolStripMenuItem("새 문서", null, (_, _) => create(module.Id)));
        file.DropDownItems.Add(new ToolStripMenuItem("열기…", null, (_, _) => open()));
        file.DropDownItems.Add(new ToolStripSeparator());
        saveMenu.Click += async (_, _) => await SaveDocumentAsync(false);
        saveAsMenu.Click += async (_, _) => await SaveDocumentAsync(true);
        file.DropDownItems.Add(saveMenu);
        file.DropDownItems.Add(saveAsMenu);
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add(new ToolStripMenuItem("닫기", null, (_, _) => Close()));
        menu.Items.Add(file);
        MainMenuStrip = menu;
        var status = new StatusStrip { ShowItemToolTips = true };
        status.Items.Add(statusLabel);
        status.Items.Add(new ToolStripStatusLabel(module.DisplayName));
        Controls.Add(editorPanel);
        Controls.Add(status);
        Controls.Add(menu);
        SetStatus("문서를 준비하고 있습니다…");
        EnableSave(false);
        resizeTimer.Tick += async (_, _) => await ResizeEditorAsync();
        statusTimer.Tick += async (_, _) => await RefreshStatusAsync();
        editorPanel.ClientSizeChanged += (_, _) => QueueResize();
        DpiChanged += (_, _) => QueueResize();
        Shown += async (_, _) => await AttachAsync();
        FormClosing += OnDocumentClosing;
        FormClosed += (_, _) =>
        {
            resizeTimer.Dispose();
            statusTimer.Dispose();
            if (IsHandleCreated) NativeWindowProperties.Remove(Handle);
        };
    }

    private async Task AttachAsync()
    {
        loading = true;
        try
        {
            worker = WorkerClient.Start(WorkerLaunch.Create(packageRoot));
            worker.CommandReceived += OnWorkerCommand;
            var size = EditorSize();
            var request = new Dictionary<string, object>
            {
                ["parentHwnd"] = editorPanel.Handle.ToInt64(), ["module"] = module.Id,
                ["width"] = size.Width, ["height"] = size.Height
            };
            if (path is not null) request["path"] = path;
            var result = await worker.SendAsync("attach", request);
            var childHwnd = result.GetProperty("childHwnd").GetInt64();
            var parentHwnd = result.GetProperty("parentHwnd").GetInt64();
            if (parentHwnd != editorPanel.Handle.ToInt64() || childHwnd == 0 || !NativeWindowProperties.IsChild(editorPanel.Handle, checked((nint)childHwnd)))
                throw new SuiteException("문서 편집기를 OpenGeul 창 안에 연결하지 못했습니다. 패키지의 Windows 런타임을 확인해 주세요.");
            NativeWindowProperties.Set(Handle, editorPanel.Handle, checked((nint)childHwnd));
            attached = true;
            sentSize = size;
            ApplyStatus(result);
            EnableSave(true);
            statusTimer.Start();
            QueueResize();
        }
        catch (Exception e)
        {
            SetStatus("문서를 열지 못했습니다.");
            await ReleaseWorkerAsync();
            Program.ShowError("문서를 열지 못했습니다. 원본 파일은 변경하지 않았습니다.\n" + e.Message, this);
        }
        finally { loading = false; }
    }

    private void OnWorkerCommand(WorkerCommand command)
    {
        if (IsDisposed || Disposing || !IsHandleCreated) return;
        try
        {
            BeginInvoke(async () =>
            {
                if (!attached || busy || closing || IsDisposed) return;
                switch (command.Command)
                {
                    case "open": open(); break;
                    case "new": create(command.Module ?? module.Id); break;
                    case "save": await SaveDocumentAsync(false); break;
                    case "saveAs": await SaveDocumentAsync(true); break;
                    case "close": Close(); break;
                }
            });
        }
        catch (InvalidOperationException) { /* Form closed between event and BeginInvoke. */ }
    }

    private Size EditorSize() => new(Math.Max(1, editorPanel.ClientSize.Width), Math.Max(1, editorPanel.ClientSize.Height));
    private void QueueResize() { if (attached && !closing) resizeTimer.Start(); }

    private async Task ResizeEditorAsync()
    {
        resizeTimer.Stop();
        if (!attached || worker is null || closing || resizeBusy || WindowState == FormWindowState.Minimized) return;
        var size = EditorSize();
        if (size == sentSize) return;
        resizeBusy = true;
        try
        {
            await worker.SendAsync("resize", new { width = size.Width, height = size.Height });
            sentSize = size;
        }
        catch (Exception e) { SetStatus("편집기 크기를 변경하지 못했습니다. " + e.Message); }
        finally
        {
            resizeBusy = false;
            if (attached && !closing && EditorSize() != size) resizeTimer.Start();
        }
    }

    private async Task RefreshStatusAsync()
    {
        if (!attached || worker is null || closing || busy || statusBusy) return;
        statusBusy = true;
        try
        {
            var result = await worker.SendAsync("status", new { });
            if (attached && !IsDisposed) ApplyStatus(result);
        }
        catch (Exception e) { statusTimer.Stop(); SetStatus("문서 상태를 확인할 수 없습니다. 문서 창을 유지합니다. " + e.Message); }
        finally { statusBusy = false; }
    }

    private void ApplyStatus(JsonElement result)
    {
        var modified = result.GetProperty("modified").GetBoolean();
        var title = result.TryGetProperty("title", out var titleValue) ? titleValue.GetString() : null;
        if (string.IsNullOrWhiteSpace(title)) title = path is null ? "새 문서" : Path.GetFileName(path);
        Text = $"{(modified ? "* " : "")}{title} — {module.DisplayName}";
        string? readinessMessage = null;
        if (result.TryGetProperty("readiness", out var readiness) && readiness.ValueKind == JsonValueKind.Object
            && readiness.TryGetProperty("message", out var message) && message.ValueKind == JsonValueKind.String)
            readinessMessage = message.GetString();
        SetStatus(DocumentStatusText.Format(module.Id, modified, path is not null, readinessMessage));
    }

    private async Task<bool> SaveDocumentAsync(bool saveAs)
    {
        if (!attached || worker is null || loading || busy) return false;
        busy = true;
        EnableSave(false);
        try
        {
            string? target = null, filter = null;
            if (saveAs || path is null)
            {
                using var dialog = new SaveFileDialog
                {
                    Title = $"{module.DisplayName} — 다른 이름으로 저장",
                    Filter = module.DialogFilter, DefaultExt = module.DefaultExtension, AddExtension = true,
                    OverwritePrompt = true, CheckPathExists = true,
                    FileName = path is null ? "새 문서." + module.DefaultExtension : Path.GetFileName(path)
                };
                if (path is not null) dialog.InitialDirectory = Path.GetDirectoryName(path);
                if (dialog.ShowDialog(this) != DialogResult.OK) return false;
                target = LocalDocumentPath.Validate(dialog.FileName);
                filter = module.SaveFilter(target);
            }
            SetStatus("저장하고 있습니다…");
            var request = new Dictionary<string, object>();
            if (target is not null) { request["path"] = target; request["filter"] = filter!; }
            var result = await worker.SendAsync("save", request);
            if (target is not null) path = target;
            ApplyStatus(result);
            return true;
        }
        catch (Exception e)
        {
            SetStatus("저장하지 못했습니다. 문서 창을 유지합니다.");
            Program.ShowError("문서를 저장하지 못했습니다. 문서 창을 유지합니다.\n" + e.Message, this);
            return false;
        }
        finally { busy = false; EnableSave(attached && !closing); }
    }

    async Task<DocumentStatus> IDocumentSession.StatusAsync()
    {
        var result = await worker!.SendAsync("status", new { });
        ApplyStatus(result);
        return new DocumentStatus(result.GetProperty("modified").GetBoolean(), Text);
    }

    async Task<bool> IDocumentSession.CloseAsync(bool discard)
    {
        var result = await worker!.SendAsync("close", new { discard });
        return result.TryGetProperty("closed", out var closed) && closed.GetBoolean()
            && (!result.TryGetProperty("closeCancelled", out var cancelled) || !cancelled.GetBoolean());
    }

    internal async Task<bool> RequestCloseAsync()
    {
        if (IsDisposed || closeApproved) return true;
        if (closing) return false;
        if (loading || busy) { SetStatus("진행 중인 문서 작업이 끝난 후 다시 닫아 주세요."); return false; }
        closing = true;
        resizeTimer.Stop(); statusTimer.Stop(); EnableSave(false);
        try
        {
            if (attached)
            {
                var result = await DocumentClose.TryAsync(this, () => Task.FromResult(ChooseClose()), () => SaveDocumentAsync(false));
                if (!result.Closed)
                {
                    if (result.Error is not null) Program.ShowError(result.Error, this);
                    return false;
                }
                attached = false;
                // The document is already safely closed; shutdown cannot discard a live document.
                try { await worker!.SendAsync("shutdown", new { }); } catch (Exception) { }
            }
            await ReleaseWorkerAsync();
            closeApproved = true;
            Close();
            return true;
        }
        finally
        {
            closing = false;
            if (!closeApproved && attached) { EnableSave(true); statusTimer.Start(); QueueResize(); }
        }
    }

    private CloseChoice ChooseClose()
    {
        var save = new TaskDialogButton("저장");
        var discard = new TaskDialogButton("저장하지 않음");
        var cancel = new TaskDialogButton("취소");
        var page = new TaskDialogPage
        {
            Caption = module.DisplayName, Heading = "변경 내용을 저장하시겠습니까?",
            Text = "저장하지 않음을 선택하면 변경 내용이 사라집니다.",
            Buttons = { save, discard, cancel }, DefaultButton = save, AllowCancel = true,
            Icon = TaskDialogIcon.Information
        };
        var selected = TaskDialog.ShowDialog(this, page);
        return selected == save ? CloseChoice.Save : selected == discard ? CloseChoice.Discard : CloseChoice.Cancel;
    }

    private async void OnDocumentClosing(object? sender, FormClosingEventArgs e)
    {
        if (closeApproved) return;
        e.Cancel = true;
        await RequestCloseAsync();
    }

    private async Task ReleaseWorkerAsync()
    {
        var ownedWorker = worker;
        worker = null;
        if (ownedWorker is null) return;
        ownedWorker.CommandReceived -= OnWorkerCommand;
        try { await ownedWorker.DisposeAsync(); }
        catch (Exception e) { SetStatus("문서 작업자 종료를 확인하지 못했습니다. " + e.Message); }
    }

    private void SetStatus(string text)
    {
        if (IsDisposed) return;
        statusLabel.Text = text.Replace('\r', ' ').Replace('\n', ' ');
        statusLabel.ToolTipText = text;
    }
    private void EnableSave(bool enabled) { saveMenu.Enabled = enabled; saveAsMenu.Enabled = enabled; }
}

internal static class NativeWindowProperties
{
    internal const string ParentProperty = "OpenGeul.Office.ParentHwnd";
    internal const string ChildProperty = "OpenGeul.Office.ChildHwnd";
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool IsChild(nint parent, nint child);
    [DllImport("user32.dll", EntryPoint = "SetPropW", CharSet = CharSet.Unicode, SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetProp(nint hwnd, string name, nint value);
    [DllImport("user32.dll", EntryPoint = "RemovePropW", CharSet = CharSet.Unicode)]
    private static extern nint RemoveProp(nint hwnd, string name);
    internal static void Set(nint form, nint parent, nint child)
    {
        if (!SetProp(form, ParentProperty, parent) || !SetProp(form, ChildProperty, child))
            throw new SuiteException("내장 편집기 창 정보를 등록할 수 없습니다.");
    }
    internal static void Remove(nint form) { RemoveProp(form, ParentProperty); RemoveProp(form, ChildProperty); }
}
