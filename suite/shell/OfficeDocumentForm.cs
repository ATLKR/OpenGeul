using System.Runtime.InteropServices;
using System.Text.Json;
using OpenGeul.Office.Core;

namespace OpenGeul.Office;

internal sealed class OfficeDocumentForm : Form, IDocumentSession
{
    private readonly string packageRoot;
    private readonly SuiteModule module;
    private readonly Action<IWin32Window> open;
    private readonly Action<string> create;
    private readonly Action home;
    private readonly Action exit;
    private readonly Panel editorPanel = new() { Dock = DockStyle.Fill, BackColor = Color.White, Name = "OfficeHostPanel", TabStop = true, Enabled = false };
    private readonly ToolStripStatusLabel statusLabel = new() { Spring = true, TextAlign = ContentAlignment.MiddleLeft, Name = "OfficeDocumentStatus" };
    private readonly System.Windows.Forms.Timer resizeTimer = new() { Interval = 100 };
    private readonly System.Windows.Forms.Timer statusTimer = new() { Interval = 1500 };
    private readonly bool closeDiagnostics = CloseDiagnosticsEnabled();
    private readonly bool nativeMenuStatusDiagnostics = !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS"));
    private readonly SaveDiagnosticsTrace saveDiagnostics = new("suite.documentSave");
    private readonly SaveDiagnosticsTrace editorFocusDiagnostics = new("suite.editorFocus");
    private readonly StandaloneSaveCloseIntent saveCloseIntent = new();
    private OwnedEditorFocus? editorFocus;
    private DocumentMenuSurface? menuSurface;
    private nint editorFocusFormHwnd, editorFocusPanelHwnd;
    private readonly int uiThreadId = Environment.CurrentManagedThreadId;
    private int closeDiagnosticCount;
    private WorkerClient? worker;
    private string? path;
    private bool attached;
    private bool loading;
    private bool busy;
    private bool closing;
    private bool closeApproved;
    private bool resizeBusy;
    private bool statusBusy;
    private bool menuFailureReported;
    private bool menuFailureQueued;
    private Exception? pendingMenuFailure;
    private WorkerClient? pendingMenuFailureWorker;
    private Size sentSize;

    internal OfficeDocumentForm(string packageRoot, SuiteModule module, string? path,
        Action<IWin32Window> open, Action<string> create, Action home, Action exit)
    {
        this.packageRoot = packageRoot;
        this.module = module;
        this.path = path;
        this.open = open;
        this.create = create;
        this.home = home;
        this.exit = exit;
        Text = $"{(path is null ? "새 문서" : Path.GetFileName(path))} — {module.DisplayName}";
        Name = "OpenGeulOfficeDocument";
        SuiteWindowIcon.Apply(this);
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96F, 96F);
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(1250, 850);
        MinimumSize = new Size(700, 500);
        var status = new StatusStrip { ShowItemToolTips = true };
        status.Items.Add(statusLabel);
        status.Items.Add(new ToolStripStatusLabel(module.DisplayName));
        Controls.Add(editorPanel);
        Controls.Add(status);
        SetStatus("문서를 준비하고 있습니다…");
        resizeTimer.Tick += async (_, _) => await ResizeEditorAsync();
        statusTimer.Tick += async (_, _) => await RefreshStatusAsync();
        editorPanel.ClientSizeChanged += (_, _) => QueueResize();
        DpiChanged += (_, _) => QueueResize();
        Shown += async (_, _) => await AttachAsync();
        FormClosing += OnDocumentClosing;
        FormClosed += (_, _) =>
        {
            ReleaseEditorFocus();
            resizeTimer.Dispose();
            statusTimer.Dispose();
            if (IsHandleCreated) NativeWindowProperties.Remove(Handle);
        };
    }

    protected override void OnLoad(EventArgs e)
    {
        base.OnLoad(e);
        InitialWindowLayout.Apply(this);
    }

    protected override void OnActivated(EventArgs e)
    {
        base.OnActivated(e);
        QueueInitialEditorFocus();
    }

    protected override void OnHandleDestroyed(EventArgs e)
    {
        try { if (IsHandleCreated) NativeWindowProperties.RemoveStartupDiagnostic(Handle); }
        catch (Exception) { /* Numeric diagnostics must not interfere with form disposal. */ }
        base.OnHandleDestroyed(e);
    }

    private async Task AttachAsync()
    {
        loading = true;
        var startupPhase = StartupPhase.WorkerLaunch;
        try
        {
            worker = WorkerClient.Start(WorkerLaunch.Create(packageRoot));
            startupPhase = StartupPhase.WorkerReply;
            worker.CommandReceived += OnWorkerCommand;
            var size = EditorSize();
            var request = new Dictionary<string, object>
            {
                ["parentHwnd"] = editorPanel.Handle.ToInt64(), ["module"] = module.Id,
                ["width"] = size.Width, ["height"] = size.Height
            };
            if (path is not null) request["path"] = path;
            var result = await worker.SendAsync("attach", request, requestTimeout: TimeSpan.FromSeconds(120));
            startupPhase = StartupPhase.ShellAttach;
            var childHwnd = result.GetProperty("childHwnd").GetInt64();
            var parentHwnd = result.GetProperty("parentHwnd").GetInt64();
            if (parentHwnd != editorPanel.Handle.ToInt64() || childHwnd == 0 || !NativeWindowProperties.IsChild(editorPanel.Handle, checked((nint)childHwnd)))
                throw new SuiteException("문서 편집기를 OpenGeul 창 안에 연결하지 못했습니다. 패키지의 Windows 런타임을 확인해 주세요.",
                    startupDiagnostic: new(StartupPhase.ShellAttach, StartupReason.ShellAttachFailed));
            menuSurface = new DocumentMenuSurface(module.Id, parentHwnd, childHwnd);
            menuSurface.RequireReady(result);
            NativeWindowProperties.Set(Handle, editorPanel.Handle, checked((nint)childHwnd));
            NativeWindowProperties.SetNativeMenuReady(Handle, false);
            editorPanel.Enabled = true;
            editorFocus = new OwnedEditorFocus(new NativeOwnedEditorFocus(Handle, editorPanel.Handle, checked((nint)childHwnd)),
                Path.Combine(packageRoot, "Office", "program", "soffice.bin"));
            editorFocusFormHwnd = Handle; editorFocusPanelHwnd = editorPanel.Handle;
            attached = true;
            sentSize = size;
            ApplyStatus(result);
            statusTimer.Start();
            QueueResize();
            // Try in this UI turn. An inactive document keeps one pending initial request.
            loading = false;
            var initialFocusOwner = editorFocus;
            TryInitialEditorFocus();
            if (!ReferenceEquals(editorFocus, initialFocusOwner) || !attached || IsDisposed || Disposing || !IsHandleCreated) return;
            NativeWindowProperties.SetNativeMenuReady(Handle, true);
            PublishNativeMenuStatus(menuSurface);
        }
        catch (Exception e)
        {
            editorPanel.Enabled = false;
            attached = false;
            if (IsHandleCreated) NativeWindowProperties.SetNativeMenuReady(Handle, false);
            SetStatus("문서를 열지 못했습니다.");
            var failedWorker = worker;
            await ReleaseWorkerAsync();
            try
            {
                Console.Error.WriteLine($"OpenGeul Office attach failed ({module.Id}).");
                Console.Error.WriteLine(e.ToString());
                Console.Error.WriteLine("Office worker stderr:\n" + (failedWorker?.Diagnostics ?? "작업자를 시작하지 못했습니다."));
                Console.Error.Flush();
            }
            catch (IOException) { /* Missing diagnostic output must not prevent the error dialog. */ }
            try
            {
                if (StartupDiagnostic.Enabled && IntPtr.Size == 8 && IsHandleCreated && !IsDisposed && !Disposing)
                    NativeWindowProperties.SetStartupDiagnostic(Handle, StartupDiagnostic.FromException(e, startupPhase).Packed);
            }
            catch (Exception) { /* The original error and owned dialog remain primary. */ }
            Program.ShowError("문서를 열지 못했습니다. 원본 파일은 변경하지 않았습니다.\n" + e.Message, this);
            closeApproved = true;
            Close();
        }
        finally { loading = false; }
    }

    private void OnWorkerCommand(WorkerCommand command)
    {
        var traceSave = command.Command is "save" or "saveAs";
        if (traceSave) TraceSave("command.received", new { commandSequence = command.DiagnosticSequence, command = command.Command });
        if (IsDisposed || Disposing || !IsHandleCreated)
        {
            if (traceSave) TraceSave("command.guarded", new { commandSequence = command.DiagnosticSequence,
                guard = IsDisposed ? "disposed" : Disposing ? "disposing" : "handleMissing" });
            return;
        }
        try
        {
            if (traceSave) TraceSave("command.enqueue", new { commandSequence = command.DiagnosticSequence });
            BeginInvoke(async () =>
            {
                if (traceSave) TraceSave("command.execute", new { commandSequence = command.DiagnosticSequence });
                if (!attached || busy || closing || IsDisposed)
                {
                    if (traceSave) TraceSave("command.guarded", new { commandSequence = command.DiagnosticSequence,
                        guard = !attached ? "notAttached" : busy ? "busy" : closing ? "closing" : "disposed" });
                    return;
                }
                switch (command.Command)
                {
                    case "open": open(this); break;
                    case "new": create(command.Module ?? module.Id); break;
                    case "save": await SaveDocumentAsync(false, command.DiagnosticSequence); break;
                    case "saveAs": await SaveDocumentAsync(true, command.DiagnosticSequence); break;
                    case "close": Close(); break;
                    case "home": await DocumentMenuSurface.CloseAndShowHomeAsync(RequestCloseAsync, home); break;
                    case "exit": exit(); break;
                }
            });
        }
        catch (InvalidOperationException e)
        {
            if (traceSave) TraceSave("command.enqueueError", new { commandSequence = command.DiagnosticSequence, exceptionType = e.GetType().FullName });
            /* Form closed between event and BeginInvoke. */
        }
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
        if (!attached || worker is null || closing || busy || statusBusy || menuFailureReported || pendingMenuFailure is not null) return;
        statusBusy = true;
        var statusWorker = worker;
        try
        {
            var statusSurface = menuSurface ?? throw new SuiteException("문서의 통합 메뉴 연결 정보를 확인할 수 없습니다.");
            var statusToken = statusSurface.StartStatusRead();
            PublishNativeMenuStatus(statusSurface);
            var result = await statusWorker.SendAsync("status", new { });
            if (attached && !IsDisposed && ReferenceEquals(worker, statusWorker))
            {
                if (!ReferenceEquals(menuSurface, statusSurface)) throw new SuiteException("문서의 통합 메뉴 연결 정보가 변경됐습니다.");
                statusSurface.ObserveStatus(result, statusToken, !closing && !busy, ApplyStatus,
                    () => PublishNativeMenuStatus(statusSurface));
            }
        }
        catch (Exception e)
        {
            if (attached && !IsDisposed && ReferenceEquals(worker, statusWorker))
            {
                statusTimer.Stop();
                pendingMenuFailure ??= e;
                pendingMenuFailureWorker ??= statusWorker;
                QueueMenuFailure();
            }
        }
        finally { statusBusy = false; }
    }

    private void PublishNativeMenuStatus(DocumentMenuSurface surface)
    {
        if (!nativeMenuStatusDiagnostics || IntPtr.Size != 8 || !IsHandleCreated || IsDisposed || Disposing) return;
        var form = Handle;
        surface.PublishStatusNotice(value => NativeWindowProperties.SetNativeMenuStatus(form, value),
            () => NativeWindowProperties.RemoveNativeMenuStatus(form));
    }

    private void QueueMenuFailure()
    {
        if (Environment.CurrentManagedThreadId != uiThreadId) return;
        if (menuFailureQueued || menuFailureReported || pendingMenuFailure is null ||
            loading || busy || closing || closeApproved || !attached || IsDisposed || Disposing || !IsHandleCreated) return;
        menuFailureQueued = true;
        try
        {
            BeginInvoke(async () =>
            {
                menuFailureQueued = false;
                if (loading || busy || closing || closeApproved || !attached || IsDisposed || Disposing || !IsHandleCreated) return;
                var failure = pendingMenuFailure;
                var sourceWorker = pendingMenuFailureWorker;
                pendingMenuFailure = null; pendingMenuFailureWorker = null;
                if (failure is not null && sourceWorker is not null && ReferenceEquals(worker, sourceWorker))
                    await FailMenuSessionAsync(failure, sourceWorker);
            });
        }
        catch (InvalidOperationException) { menuFailureQueued = false; }
    }

    private async Task FailMenuSessionAsync(Exception error, WorkerClient failedWorker)
    {
        if (Environment.CurrentManagedThreadId != uiThreadId) return;
        if (menuFailureReported || IsDisposed || Disposing || !IsHandleCreated || !attached ||
            closing || busy || !ReferenceEquals(worker, failedWorker)) return;
        menuFailureReported = true;
        statusTimer.Stop();
        NativeWindowProperties.SetNativeMenuReady(Handle, false);
        SetStatus("통합 메뉴 연결 오류 · 문서 세션을 종료해야 합니다.");
        Program.ShowError("문서의 통합 메뉴 또는 작업자 연결을 확인할 수 없습니다. 이 문서 세션을 종료합니다.\n" + error.Message, this);
        if (!IsDisposed && !Disposing && ReferenceEquals(worker, failedWorker) && !await RequestCloseAsync())
            SetStatus("통합 메뉴 연결 오류 · 저장 또는 닫기가 취소되어 문서와 전용 프로필을 유지합니다.");
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
        var text = DocumentStatusText.Format(module.Id, modified, path is not null, readinessMessage);
        SetStatus(menuFailureReported ? "통합 메뉴 연결 오류 · " + text : text);
    }

    private async Task<bool> SaveDocumentAsync(bool saveAs, long? commandSequence = null)
    {
        TraceSave("save.begin", new { commandSequence, saveAs });
        if (!attached || worker is null || loading || busy)
        {
            TraceSave("save.guarded", new { commandSequence,
                guard = !attached ? "notAttached" : worker is null ? "workerMissing" : loading ? "loading" : "busy" });
            return false;
        }
        var saveWorker = worker;
        var saveHwnd = IsHandleCreated ? Handle : 0;
        try
        {
            return await saveCloseIntent.RunAsync(saveWorker, closing,
                () => SaveDocumentCoreAsync(saveAs, commandSequence, saveWorker),
                () => worker,
                () => Environment.CurrentManagedThreadId == uiThreadId && saveHwnd != 0 &&
                    !IsDisposed && !Disposing && IsHandleCreated && Handle == saveHwnd &&
                    attached && !loading && !busy && !closing && !closeApproved,
                async () => { TraceClose("requestClose.deferredSave"); await RequestCloseAsync(); });
        }
        finally { QueueMenuFailure(); }
    }

    private async Task<bool> SaveDocumentCoreAsync(bool saveAs, long? commandSequence, WorkerClient saveWorker)
    {
        busy = true;
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
                TraceSave("save.dialogBegin", new { commandSequence });
                var dialogResult = dialog.ShowDialog(this);
                TraceSave("save.dialogEnd", new { commandSequence, result = dialogResult.ToString() });
                if (dialogResult != DialogResult.OK)
                {
                    TraceSave("save.dialogCancelled", new { commandSequence });
                    return false;
                }
                target = LocalDocumentPath.Validate(dialog.FileName);
                filter = module.SaveFilter(target);
            }
            SetStatus("저장하고 있습니다…");
            var request = new Dictionary<string, object>();
            if (target is not null) { request["path"] = target; request["filter"] = filter!; }
            TraceSave("save.workerRequest", new { commandSequence });
            var result = await saveWorker.SendAsync("save", request, diagnosticCommandSequence: commandSequence);
            if (target is not null) path = target;
            ApplyStatus(result);
            TraceSave("save.end", new { commandSequence, ok = true });
            return true;
        }
        catch (Exception e)
        {
            TraceSave("save.error", new { commandSequence, exceptionType = e.GetType().FullName });
            SetStatus("저장하지 못했습니다. 문서 창을 유지합니다.");
            Program.ShowError("문서를 저장하지 못했습니다. 문서 창을 유지합니다.\n" + e.Message, this);
            return false;
        }
        finally { busy = false; }
    }

    Task<DocumentStatus> IDocumentSession.StatusAsync() => ReadCloseStatusAsync("status", "status");
    Task<DocumentStatus> IDocumentSession.PrepareCloseAsync() => ReadCloseStatusAsync("prepare-close", "prepareClose");

    private async Task<DocumentStatus> ReadCloseStatusAsync(string command, string traceStage)
    {
        TraceClose(traceStage + ".begin");
        try
        {
            var result = await worker!.SendAsync(command, new { });
            ApplyStatus(result);
            var status = new DocumentStatus(result.GetProperty("modified").GetBoolean(), Text);
            TraceClose(traceStage + ".end", new { modified = status.Modified });
            return status;
        }
        catch (Exception e)
        {
            TraceClose(traceStage + ".error", new { exceptionType = e.GetType().FullName });
            throw;
        }
    }

    async Task<CloseResult> IDocumentSession.CloseAsync(bool discard)
    {
        TraceClose("sessionClose.begin", new { discard });
        try
        {
            var result = await worker!.SendAsync("close", new { discard });
            var outcome = DocumentClose.FromWorkerResult(result);
            TraceClose("sessionClose.end", new { discard, closed = outcome.Closed, hasWarning = outcome.Warning is not null });
            return outcome;
        }
        catch (Exception e)
        {
            TraceClose("sessionClose.error", new { discard, exceptionType = e.GetType().FullName });
            throw;
        }
    }

    internal async Task<bool> RequestCloseAsync()
    {
        TraceClose("requestClose.enter");
        if (IsDisposed || closeApproved) { TraceClose("requestClose.guarded", new { guard = "disposedOrApproved" }); return true; }
        if (closing) { TraceClose("requestClose.guarded", new { guard = "closing" }); return false; }
        if (loading) { TraceClose("requestClose.guarded", new { guard = "loadingOrBusy" }); SetStatus("진행 중인 문서 작업이 끝난 후 다시 닫아 주세요."); return false; }
        if (Disposing) { TraceClose("requestClose.guarded", new { guard = "disposing" }); return false; }
        if (busy)
        {
            var deferred = Environment.CurrentManagedThreadId == uiThreadId && IsHandleCreated &&
                worker is not null && saveCloseIntent.RequestClose(worker);
            TraceClose("requestClose.guarded", new { guard = deferred ? "standaloneSaveDeferred" : "loadingOrBusy" });
            if (!deferred) SetStatus("진행 중인 문서 작업이 끝난 후 다시 닫아 주세요.");
            return false;
        }
        closing = true;
        resizeTimer.Stop(); statusTimer.Stop();
        try
        {
            if (attached)
            {
                TraceClose("documentClose.begin");
                var result = await DocumentClose.TryAsync(this, () => Task.FromResult(ChooseClose()), () => SaveDocumentAsync(false));
                TraceClose("documentClose.result", new { closed = result.Closed, hasError = result.Error is not null, hasWarning = result.Warning is not null });
                if (!result.Closed)
                {
                    if (result.Error is not null) Program.ShowError(result.Error, this);
                    return false;
                }
                attached = false;
                if (result.Warning is not null)
                    MessageBox.Show(this, result.Warning, "문서 종료 확인", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                // The document model is confirmed closed; release only this form's worker.
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
            if (!closeApproved && attached)
            {
                if (!menuFailureReported && pendingMenuFailure is null) statusTimer.Start();
                QueueResize(); QueueMenuFailure();
            }
            TraceClose("requestClose.finally");
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
        TraceClose("chooseClose.before");
        try
        {
            var selected = TaskDialog.ShowDialog(this, page);
            var choice = selected == save ? CloseChoice.Save : selected == discard ? CloseChoice.Discard : CloseChoice.Cancel;
            TraceClose("chooseClose.after", new { choice = choice.ToString() });
            return choice;
        }
        catch (Exception e)
        {
            TraceClose("chooseClose.error", new { exceptionType = e.GetType().FullName });
            throw;
        }
    }

    private async void OnDocumentClosing(object? sender, FormClosingEventArgs e)
    {
        TraceClose("formClosing.enter", new { reason = e.CloseReason.ToString(), cancel = e.Cancel });
        if (closeApproved) return;
        e.Cancel = true;
        await RequestCloseAsync();
    }

    protected override void WndProc(ref Message m)
    {
        if (m.Msg == 0x0010) TraceClose("wmClose.received", new { messageHwnd = m.HWnd.ToInt64() });
        base.WndProc(ref m);
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if ((keyData == (Keys.Control | Keys.S) || keyData == (Keys.Control | Keys.Shift | Keys.S)) &&
            (msg.HWnd == Handle || msg.HWnd == editorPanel.Handle) && attached && worker is not null &&
            !loading && !busy && !closing && !closeApproved && !IsDisposed && !Disposing &&
            Enabled && Visible && ActiveForm == this)
        {
            _ = SaveDocumentAsync(keyData == (Keys.Control | Keys.Shift | Keys.S));
            return true;
        }
        if ((keyData & Keys.KeyCode) == Keys.F6 && keyData != (Keys.Control | Keys.F6) && editorFocus is not null &&
            editorFocusFormHwnd != 0 && editorFocusPanelHwnd != 0 &&
            (msg.HWnd == editorFocusFormHwnd || msg.HWnd == editorFocusPanelHwnd))
        {
            editorFocusDiagnostics.Write("f6.unrouted", new { reason = "modifier mismatch", keyData = (int)keyData,
                message = msg.Msg, messageHwnd = msg.HWnd.ToInt64(), wParam = msg.WParam.ToInt64(), lParam = msg.LParam.ToInt64(),
                originalFormHwnd = editorFocusFormHwnd.ToInt64(), originalPanelHwnd = editorFocusPanelHwnd.ToInt64() },
                worker?.ProcessId, worker?.DiagnosticTraceId);
        }
        if (keyData == (Keys.Control | Keys.F6) && editorFocus is not null &&
            (msg.HWnd == Handle || msg.HWnd == editorPanel.Handle))
        {
            var available = EditorFocusAvailable();
            var result = editorFocus.Route((int)keyData, msg.HWnd.ToInt64(), available);
            editorFocusDiagnostics.Write("ctrlF6", new { keyData = (int)keyData, message = msg.Msg,
                messageHwnd = msg.HWnd.ToInt64(), wParam = msg.WParam.ToInt64(), lParam = msg.LParam.ToInt64(), available, result },
                worker?.ProcessId, worker?.DiagnosticTraceId);
            return true;
        }
        return base.ProcessCmdKey(ref msg, keyData);
    }

    private bool EditorFocusAvailable() => Environment.CurrentManagedThreadId == uiThreadId &&
        attached && worker is not null && !loading && !busy && !closing && !closeApproved &&
        !IsDisposed && !Disposing && IsHandleCreated && Enabled && Visible && !Modal && ActiveForm == this;

    private void TryInitialEditorFocus()
    {
        var owned = editorFocus;
        if (owned is null) return;
        var available = EditorFocusAvailable();
        var result = owned.TryInitialFocus(available);
        editorFocusDiagnostics.Write("initial", new { available, pending = owned.InitialFocusPending, result }, worker?.ProcessId, worker?.DiagnosticTraceId);
    }

    private void QueueInitialEditorFocus()
    {
        var owned = editorFocus;
        if (!attached || loading || owned is null || !owned.InitialFocusPending || IsDisposed || Disposing || !IsHandleCreated) return;
        // Run after WinForms finishes activation and normal focus restoration. The retained
        // owner coalesces callbacks and rechecks all native guards at execution time.
        var queued = owned.QueueInitialFocus(callback => BeginInvoke(callback),
            () => ReferenceEquals(editorFocus, owned) && EditorFocusAvailable(),
            result => editorFocusDiagnostics.Write("initial.activation", new { pending = owned.InitialFocusPending, result },
                worker?.ProcessId, worker?.DiagnosticTraceId));
        editorFocusDiagnostics.Write("initial.queued", new { queued, pending = owned.InitialFocusPending }, worker?.ProcessId, worker?.DiagnosticTraceId);
    }

    private void ReleaseEditorFocus()
    {
        var owned = editorFocus; editorFocus = null; editorFocusFormHwnd = editorFocusPanelHwnd = 0; owned?.Dispose();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) { saveCloseIntent.Invalidate(); ReleaseEditorFocus(); }
        base.Dispose(disposing);
    }

    private static bool CloseDiagnosticsEnabled()
    {
        try { return !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("OPENGEUL_SUITE_DIAGNOSTICS")); }
        catch (Exception) { return false; }
    }

    private void TraceClose(string stage, object? details = null)
    {
        if (!closeDiagnostics) return;
        try
        {
            // Limit diagnostic output per form, including failed output attempts.
            var sequence = Interlocked.Increment(ref closeDiagnosticCount);
            if (sequence > 128) return;
            var managedThreadId = Environment.CurrentManagedThreadId;
            Console.Error.WriteLine(JsonSerializer.Serialize(new
            {
                @event = "suite.documentClose", stage, sequence, utc = DateTimeOffset.UtcNow,
                processId = Environment.ProcessId, module = module.Id,
                managedThreadId, uiThreadId, isUiThread = managedThreadId == uiThreadId,
                hwnd = IsHandleCreated ? Handle.ToInt64() : 0,
                loading, busy, closing, attached, closeApproved, statusBusy, resizeBusy,
                disposed = IsDisposed, disposing = Disposing, workerPresent = worker is not null,
                details
            }));
            Console.Error.Flush();
        }
        catch (Exception) { /* Diagnostic failures must not change document close behavior. */ }
    }

    private void TraceSave(string stage, object? details = null)
    {
        if (!saveDiagnostics.Enabled) return;
        try
        {
            var managedThreadId = Environment.CurrentManagedThreadId;
            var isUiThread = managedThreadId == uiThreadId;
            saveDiagnostics.Write(stage, new
            {
                module = module.Id, uiThreadId, isUiThread,
                hwnd = isUiThread && IsHandleCreated ? Handle.ToInt64() : 0,
                loading, busy, closing, attached, statusBusy, resizeBusy,
                disposed = IsDisposed, disposing = Disposing, workerPresent = worker is not null,
                details
            }, worker?.ProcessId, worker?.DiagnosticTraceId);
        }
        catch (Exception) { /* Diagnostic snapshots must not change save behavior. */ }
    }

    private async Task ReleaseWorkerAsync()
    {
        saveCloseIntent.Invalidate();
        ReleaseEditorFocus();
        pendingMenuFailure = null; pendingMenuFailureWorker = null;
        menuSurface = null;
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
}

internal static class NativeWindowProperties
{
    internal const string ParentProperty = "OpenGeul.Office.ParentHwnd";
    internal const string ChildProperty = "OpenGeul.Office.ChildHwnd";
    internal const string NativeMenuReadyProperty = "OpenGeul.Office.NativeMenuReady";
    internal const string NativeMenuStatusProperty = "OpenGeul.Office.NativeMenuStatusV1";
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool IsChild(nint parent, nint child);
    [DllImport("user32.dll", EntryPoint = "SetPropW", CharSet = CharSet.Unicode, SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetProp(nint hwnd, string name, nint value);
    [DllImport("user32.dll", EntryPoint = "RemovePropW", CharSet = CharSet.Unicode)]
    private static extern nint RemoveProp(nint hwnd, string name);
    internal static void Set(nint form, nint parent, nint child)
    {
        if (!SetProp(form, ParentProperty, parent) || !SetProp(form, ChildProperty, child))
            throw new SuiteException("내장 편집기 창 정보를 등록할 수 없습니다.", startupDiagnostic:
                new(StartupPhase.ShellAttach, StartupReason.ShellAttachFailed, StartupDiagnostic.KnownNativeCode(Marshal.GetLastWin32Error())));
    }
    internal static void SetStartupDiagnostic(nint form, ulong value) => SetProp(form, StartupDiagnostic.PropertyName, checked((nint)value));
    internal static void RemoveStartupDiagnostic(nint form) => RemoveProp(form, StartupDiagnostic.PropertyName);
    internal static bool SetNativeMenuStatus(nint form, ulong value) => SetProp(form, NativeMenuStatusProperty, checked((nint)value));
    internal static void RemoveNativeMenuStatus(nint form) => RemoveProp(form, NativeMenuStatusProperty);
    internal static void SetNativeMenuReady(nint form, bool ready)
    {
        // A mode hint for native UI proof, never evidence that the menu was used.
        try { _ = SetProp(form, NativeMenuReadyProperty, ready ? 1 : 0); }
        catch (Exception) { /* Hint failure must not change document behavior. */ }
    }
    internal static void Remove(nint form)
    {
        RemoveProp(form, ParentProperty); RemoveProp(form, ChildProperty); RemoveProp(form, NativeMenuReadyProperty);
        RemoveNativeMenuStatus(form);
    }
}
