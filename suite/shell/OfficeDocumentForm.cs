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
    private readonly SaveDiagnosticsTrace initialFocusFlowDiagnostics = new("suite.initialEditorFocusFlow");
    private readonly SaveDiagnosticsTrace initialFocusStatusDiagnostics = new("suite.initialEditorFocusStatus");
    private int initialFocusObservationCount;
    private InitialFocusCounters? initialFocusCounters;
    private readonly int[] initialFocusPreOwnerCounts = new int[3];
    private int initialFocusPreOwnerOverflow, initialFocusOwnerGeneration;
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
        CountInitialFocusIngress(0);
        var observedOwner = editorFocusDiagnostics.Enabled ? editorFocus : null;
        var pendingBefore = observedOwner?.InitialFocusPending == true;
        var observedForm = pendingBefore ? editorFocusFormHwnd : 0;
        var observedPanel = pendingBefore ? editorFocusPanelHwnd : 0;
        var receivedHwnd = pendingBefore && IsHandleCreated ? Handle : 0;
        var flow = pendingBefore ? CreateInitialFocusFlow(1, true, pendingBefore) : null;
        WriteInitialFocusFlow(flow, 1);
        base.OnActivated(e);
        TraceInitialActivation(1, receivedHwnd, observedOwner, pendingBefore, observedForm, observedPanel);
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
            StartInitialFocusCounters(editorFocus, childHwnd);
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
        var statusFocusCounters = InitialFocusCountersFor(editorFocus);
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
                WriteInitialFocusPrefix(statusFocusCounters);
                WriteInitialFocusStatus(statusFocusCounters);
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
        var appActivated = m.Msg == 0x001C && m.WParam != 0;
        // WinForms can retain Active=true while the live foreground form was elsewhere.
        // A later native activation need not raise another managed Activated event.
        var windowActivated = m.Msg == 0x0006 && (m.WParam.ToInt64() & 0xffff) is 1 or 2;
        if (m.Msg == 0x001C) CountInitialFocusIngress(appActivated ? 1 : 2);
        var activationHwnd = m.HWnd;
        var initialFocusOwner = editorFocus;
        var initialFocusGeneration = initialFocusOwnerGeneration;
        var pendingBefore = editorFocusDiagnostics.Enabled && initialFocusOwner?.InitialFocusPending == true;
        var observedForm = pendingBefore ? editorFocusFormHwnd : 0;
        var observedPanel = pendingBefore ? editorFocusPanelHwnd : 0;
        var activationSource = m.Msg == 0x001C ? (appActivated ? 2 : 5) : m.Msg == 0x0021 ? 3 : 0;
        var flow = activationSource != 0 && pendingBefore ? CreateInitialFocusFlow(activationSource, true, pendingBefore) : null;
        WriteInitialFocusFlow(flow, 1);
        if (m.Msg == 0x0010) TraceClose("wmClose.received", new { messageHwnd = m.HWnd.ToInt64() });
        base.WndProc(ref m);
        if (activationSource != 0)
            TraceInitialActivation(activationSource, activationHwnd, initialFocusOwner, pendingBefore, observedForm, observedPanel);
        if ((appActivated || windowActivated) && initialFocusOwner is not null && initialFocusOwner.InitialFocusPending &&
            ReferenceEquals(editorFocus, initialFocusOwner) && initialFocusOwnerGeneration == initialFocusGeneration &&
            !closing && !closeApproved && !IsDisposed && !Disposing && IsHandleCreated &&
            activationHwnd == editorFocusFormHwnd && activationHwnd == Handle)
            QueueInitialEditorFocus();
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

    private bool EditorFocusAvailable(InitialFocusFlow? flow = null, InitialFocusCounters? counters = null, int sourceCode = 0)
    {
        flow?.Begin(3);
        WriteInitialFocusFlow(flow, 6);
        try
        {
            var available = InitialFocusGate(flow, 1, Environment.CurrentManagedThreadId == uiThreadId) &&
                InitialFocusGate(flow, 2, attached) && InitialFocusGate(flow, 3, worker is not null) &&
                InitialFocusGate(flow, 4, !loading) && InitialFocusGate(flow, 5, !busy) &&
                InitialFocusGate(flow, 6, !closing) && InitialFocusGate(flow, 7, !closeApproved) &&
                InitialFocusGate(flow, 8, !IsDisposed) && InitialFocusGate(flow, 9, !Disposing) &&
                InitialFocusGate(flow, 10, IsHandleCreated) && InitialFocusGate(flow, 11, Enabled) &&
                InitialFocusGate(flow, 12, Visible) && InitialFocusGate(flow, 13, !Modal) &&
                InitialFocusGate(flow, 14, ActiveForm == this);
            flow?.Complete();
            ObserveInitialFocusAvailability(counters, flow, available, sourceCode);
            return available;
        }
        finally { WriteInitialFocusFlow(flow, 7); }
    }

    private void TryInitialEditorFocus()
    {
        var owned = editorFocus;
        if (owned is null) return;
        var counters = InitialFocusCountersFor(owned);
        var flow = CreateInitialFocusFlow(0, false, false);
        WriteInitialFocusFlow(flow, 1);
        var available = EditorFocusAvailable(flow, counters, 0);
        var result = owned.TryInitialFocus(available);
        var pending = owned.InitialFocusPending;
        ObserveInitialFocusResult(counters, result, pending);
        var focusWorkerPid = worker?.ProcessId; var focusTraceId = worker?.DiagnosticTraceId;
        if (counters is not null) { counters.WorkerPid = focusWorkerPid; counters.TraceId = focusTraceId; }
        editorFocusDiagnostics.Write("initial", new { available, pending, result }, focusWorkerPid, focusTraceId);
        flow?.Pending(pending);
        WriteInitialFocusFlow(flow, 12);
    }

    private void QueueInitialEditorFocus()
    {
        var owned = editorFocus;
        var counters = InitialFocusCountersFor(owned);
        counters?.Count(6);
        var pendingBefore = editorFocusDiagnostics.Enabled && owned?.InitialFocusPending == true;
        if (pendingBefore)
            TraceInitialActivation(4, editorFocusFormHwnd, owned, true, editorFocusFormHwnd, editorFocusPanelHwnd);
        var flow = pendingBefore ? CreateInitialFocusFlow(4, true, pendingBefore) : null;
        WriteInitialFocusFlow(flow, 1);
        flow?.Begin(1);
        if (InitialFocusQueueGate(flow, 1, !attached) || InitialFocusQueueGate(flow, 2, loading) ||
            InitialFocusQueueGate(flow, 3, owned is null) || InitialFocusQueueGate(flow, 4, !owned!.InitialFocusPending) ||
            InitialFocusQueueGate(flow, 5, IsDisposed) || InitialFocusQueueGate(flow, 6, Disposing) ||
            InitialFocusQueueGate(flow, 7, !IsHandleCreated))
        {
            flow?.Complete(); WriteInitialFocusFlow(flow, 2);
            counters?.Count(7);
            return;
        }
        flow?.Complete(); WriteInitialFocusFlow(flow, 2);
        // Run after WinForms finishes activation and normal focus restoration. The retained
        // owner coalesces callbacks and rechecks all native guards at execution time.
        counters?.Count(8);
        var queued = owned!.QueueInitialFocus(callback =>
            {
                WriteInitialFocusFlow(flow, 3);
                counters?.Count(11);
                BeginInvoke((Action)(() =>
                {
                    counters?.Count(13);
                    flow?.ForgetPending();
                    WriteInitialFocusFlow(flow, 5);
                    try { callback(); }
                    finally
                    {
                        WriteInitialFocusFlow(flow, 10);
                        counters?.Count(14);
                        if (counters?.Retired == 1) WriteInitialFocusFinal(counters);
                    }
                }));
                counters?.Count(12);
                WriteInitialFocusFlow(flow, 4);
            },
            () => ObserveInitialFocusOwner(flow, ReferenceEquals(editorFocus, owned)) && EditorFocusAvailable(flow, counters, 4),
            result =>
            {
                WriteInitialFocusFlow(flow, 8);
                var callbackPending = owned!.InitialFocusPending;
                ObserveInitialFocusResult(counters, result, callbackPending);
                editorFocusDiagnostics.Write("initial.activation", new { pending = callbackPending, result }, worker?.ProcessId, worker?.DiagnosticTraceId);
                flow?.Pending(callbackPending);
                WriteInitialFocusFlow(flow, 9);
            });
        counters?.Count(queued ? 9 : 10);
        var pending = owned!.InitialFocusPending;
        counters?.ObservePending(pending);
        editorFocusDiagnostics.Write("initial.queued", new { queued, pending }, worker?.ProcessId, worker?.DiagnosticTraceId);
        flow?.Pending(pending); flow?.QueueReturn(queued);
        WriteInitialFocusFlow(flow, 11);
    }

    private sealed class InitialFocusFlow(int observationId, int sourceCode, long form, long panel)
    {
        internal readonly int ObservationId = observationId, SourceCode = sourceCode;
        internal readonly long Form = form, Panel = panel;
        internal int Group, EvaluatedMask, TrueMask, FirstRejectId;
        internal bool EvaluationComplete, PendingKnown, PendingValue, QueueReturnKnown, QueueReturnValue;
        internal void Begin(int group) { Group = group; EvaluatedMask = TrueMask = FirstRejectId = 0; EvaluationComplete = false; }
        internal void Record(int id, bool value)
        {
            EvaluatedMask |= 1 << (id - 1);
            if (value) TrueMask |= 1 << (id - 1);
            if (FirstRejectId == 0 && (Group == 1 ? value : !value)) FirstRejectId = id;
        }
        internal void Complete() => EvaluationComplete = true;
        internal void Pending(bool value) { PendingKnown = true; PendingValue = value; }
        internal void ForgetPending() { PendingKnown = PendingValue = false; }
        internal void QueueReturn(bool value) { QueueReturnKnown = true; QueueReturnValue = value; }
    }

    private InitialFocusFlow? CreateInitialFocusFlow(int source, bool pendingKnown, bool pending)
    {
        try
        {
            // Cached HWNDs and already evaluated values only; this never creates or queries a handle.
            if (!initialFocusFlowDiagnostics.Enabled || editorFocusFormHwnd == 0 || editorFocusPanelHwnd == 0 || initialFocusObservationCount >= 128) return null;
            var flow = new InitialFocusFlow(++initialFocusObservationCount, source, editorFocusFormHwnd.ToInt64(), editorFocusPanelHwnd.ToInt64());
            if (pendingKnown) flow.Pending(pending);
            return flow;
        }
        catch (Exception) { return null; }
    }

    private static bool InitialFocusGate(InitialFocusFlow? flow, int id, bool value)
    {
        try { flow?.Record(id, value); }
        catch (Exception) { /* Observations never change the evaluated bool. */ }
        return value;
    }

    private static bool InitialFocusQueueGate(InitialFocusFlow? flow, int id, bool value)
    {
        if (id == 4) flow?.Pending(!value);
        return InitialFocusGate(flow, id, value);
    }

    private bool ObserveInitialFocusOwner(InitialFocusFlow? flow, bool value)
    {
        flow?.Begin(2);
        InitialFocusGate(flow, 1, value); flow?.Complete();
        WriteInitialFocusFlow(flow, 7);
        return value;
    }

    private void WriteInitialFocusFlow(InitialFocusFlow? flow, int phase)
    {
        if (flow is null) return;
        try
        {
            initialFocusFlowDiagnostics.Write("observe", new
            {
                schemaVersion = 1, observationId = flow.ObservationId, sourceCode = flow.SourceCode, phaseCode = phase,
                gateGroupCode = flow.Group, evaluatedMask = flow.EvaluatedMask, trueMask = flow.TrueMask, firstRejectId = flow.FirstRejectId,
                evaluationComplete = flow.EvaluationComplete, pendingKnown = flow.PendingKnown, pending = flow.PendingValue,
                queueReturnKnown = flow.QueueReturnKnown, queueReturn = flow.QueueReturnValue,
                originalFormHwnd = flow.Form, originalPanelHwnd = flow.Panel
            }, worker?.ProcessId, worker?.DiagnosticTraceId);
        }
        catch (Exception) { /* Numeric diagnostics never change activation, availability or posting. */ }
    }

    private void TraceInitialActivation(int sourceCode, nint receivedHwnd, OwnedEditorFocus? ownerBefore,
        bool pendingBefore, nint originalFormHwnd, nint originalPanelHwnd)
    {
        if (!editorFocusDiagnostics.Enabled || !pendingBefore || ownerBefore is null) return;
        try
        {
            // These rows observe ingress and existing queue guards only. A mouse
            // activation observation never queues or transfers editor focus.
            var currentWorker = worker;
            if (currentWorker is null || !IsHandleCreated || originalFormHwnd == 0 || originalPanelHwnd == 0) return;
            var currentOwner = editorFocus;
            var pending = currentOwner?.InitialFocusPending == true;
            var ownerSame = ReferenceEquals(currentOwner, ownerBefore);
            var rejectBitmask = (!attached ? 1 : 0) | (loading ? 2 : 0) | (currentOwner is null ? 4 : 0) |
                (!pending ? 8 : 0) | (IsDisposed ? 16 : 0) | (Disposing ? 32 : 0) | (!IsHandleCreated ? 64 : 0) |
                (!ownerSame ? 128 : 0) | (receivedHwnd != originalFormHwnd ? 256 : 0);
            editorFocusDiagnostics.Write("initial.activationObserved", new
            {
                sourceCode, rejectBitmask, pendingBefore, pending,
                originalFormHwnd = originalFormHwnd.ToInt64(), originalPanelHwnd = originalPanelHwnd.ToInt64(),
                receivedHwnd = receivedHwnd.ToInt64(), ownerSame
            }, currentWorker.ProcessId, currentWorker.DiagnosticTraceId);
        }
        catch (Exception) { /* Numeric observations must not change activation or queue behavior. */ }
    }

    // Diagnostic-only retained owner context. Every update is bounded and must
    // leave the original focus/availability/queue decision untouched.
    private sealed class InitialFocusCounters(OwnedEditorFocus owner, int generation, long form, long panel,
        long child, int managedThread)
    {
        internal readonly OwnedEditorFocus Owner = owner;
        internal readonly int Generation = generation, ManagedThread = managedThread;
        internal readonly long Form = form, Panel = panel, Child = child;
        internal int? WorkerPid;
        internal string? TraceId;
        internal readonly int[] Counts = new int[16];
        internal int OverflowMask, SnapshotRevision, IdentityKnown, OwnerChanged, Retired, DisposeReturned, UpdateFailed;
        internal int ShellPid, OfficePid, PendingKnown, PendingValue, AvailabilityKnown, AvailabilityValue, MaskKnown;
        internal int AvailabilitySource, EvaluatedMask, TrueMask, FirstReject, EvaluationComplete;
        internal long ShellBirth, OfficeBirth;
        internal uint ShellThread, EditorThread;

        internal void Count(int index)
        {
            try
            {
                if (Counts[index] < 65535) Counts[index]++;
                else OverflowMask |= 1 << index;
            }
            catch (Exception) { UpdateFailed = 1; }
        }

        internal void ObservePending(bool pending)
        {
            PendingKnown = 1; PendingValue = pending ? 1 : 0;
        }

        internal void ObserveResult(EditorFocusResult result, bool pending)
        {
            try
            {
                ObservePending(pending);
                var before = result.Before;
                if (before is null) return;
                if (before.Form.Hwnd != Form || before.Panel.Hwnd != Panel || before.Child.Hwnd != Child ||
                    before.Shell.Pid <= 0 || before.Engine.Pid <= 0 || before.Shell.Pid == before.Engine.Pid ||
                    before.Shell.CreationTime <= 0 || before.Engine.CreationTime < before.Shell.CreationTime ||
                    before.Form.ThreadId == 0 || before.Child.ThreadId == 0)
                { OwnerChanged = 1; return; }
                if (IdentityKnown == 1 && (ShellPid != before.Shell.Pid || OfficePid != before.Engine.Pid ||
                    ShellBirth != before.Shell.CreationTime || OfficeBirth != before.Engine.CreationTime ||
                    ShellThread != before.Form.ThreadId || EditorThread != before.Child.ThreadId))
                { OwnerChanged = 1; return; }
                ShellPid = before.Shell.Pid; OfficePid = before.Engine.Pid;
                ShellBirth = before.Shell.CreationTime; OfficeBirth = before.Engine.CreationTime;
                ShellThread = before.Form.ThreadId; EditorThread = before.Child.ThreadId;
                IdentityKnown = 1;
            }
            catch (Exception) { UpdateFailed = 1; }
        }
    }

    private InitialFocusCounters? InitialFocusCountersFor(OwnedEditorFocus? owner)
    {
        var counters = initialFocusCounters;
        return counters is not null && ReferenceEquals(counters.Owner, owner) ? counters : null;
    }

    private void StartInitialFocusCounters(OwnedEditorFocus owner, long child)
    {
        try
        {
            if (!initialFocusFlowDiagnostics.Enabled) return;
            if (initialFocusCounters is not null) initialFocusCounters.OwnerChanged = 1;
            initialFocusCounters = null;
            if (initialFocusOwnerGeneration >= 128) return;
            var counters = new InitialFocusCounters(owner, ++initialFocusOwnerGeneration,
                editorFocusFormHwnd.ToInt64(), editorFocusPanelHwnd.ToInt64(), child,
                uiThreadId);
            Array.Copy(initialFocusPreOwnerCounts, counters.Counts, 3);
            counters.OverflowMask = initialFocusPreOwnerOverflow;
            initialFocusCounters = counters;
        }
        catch (Exception) { /* Missing context remains unknown; no focus decision changes. */ }
    }

    private void CountInitialFocusIngress(int index)
    {
        try
        {
            if (!initialFocusFlowDiagnostics.Enabled) return;
            var counters = InitialFocusCountersFor(editorFocus);
            if (counters is not null) counters.Count(index + 3);
            else if (initialFocusPreOwnerCounts[index] < 65535) initialFocusPreOwnerCounts[index]++;
            else initialFocusPreOwnerOverflow |= 1 << index;
        }
        catch (Exception) { if (initialFocusCounters is not null) initialFocusCounters.UpdateFailed = 1; }
    }

    private void ObserveInitialFocusAvailability(InitialFocusCounters? counters, InitialFocusFlow? flow, bool available, int source)
    {
        if (counters is null) return;
        try
        {
            counters.Count(15); counters.AvailabilityKnown = 1; counters.AvailabilityValue = available ? 1 : 0;
            counters.AvailabilitySource = source;
            counters.MaskKnown = flow is not null && flow.Group == 3 && flow.EvaluationComplete ? 1 : 0;
            counters.EvaluatedMask = counters.MaskKnown == 1 ? flow!.EvaluatedMask : 0;
            counters.TrueMask = counters.MaskKnown == 1 ? flow!.TrueMask : 0;
            counters.FirstReject = counters.MaskKnown == 1 ? flow!.FirstRejectId : 0;
            counters.EvaluationComplete = counters.MaskKnown;
        }
        catch (Exception) { counters.UpdateFailed = 1; }
    }

    private void ObserveInitialFocusResult(InitialFocusCounters? counters, EditorFocusResult result, bool pending)
    {
        if (counters is null) return;
        if (!ReferenceEquals(editorFocus, counters.Owner)) counters.OwnerChanged = 1;
        counters.ObserveResult(result, pending);
    }

    private void WriteInitialFocusPrefix(InitialFocusCounters? counters)
    {
        // Copy this retained owner's counters only after the existing status
        // completion. No fresh focus/availability/native observation is made.
        if (counters is null || counters.Retired != 0 || counters.DisposeReturned != 0 ||
            !ReferenceEquals(editorFocus, counters.Owner)) return;
        WriteInitialFocusFinal(counters, prefix: true);
    }

    private void WriteInitialFocusFinal(InitialFocusCounters? counters, bool prefix = false)
    {
        if (counters is null) return;
        try
        {
            if (counters.SnapshotRevision < 65535) counters.SnapshotRevision++;
            else counters.OverflowMask |= 1 << 16;
            var count = counters.Counts;
            initialFocusFlowDiagnostics.Write(prefix ? "prefix" : "final", new
            {
                schemaVersion = 2, snapshotKindCode = prefix ? 1 : 2,
                ownerGeneration = counters.Generation, identityKnown = counters.IdentityKnown,
                ownerChanged = counters.OwnerChanged, retired = counters.Retired, disposeReturned = counters.DisposeReturned,
                updateFailed = counters.UpdateFailed, cap = 65535, overflowMask = counters.OverflowMask,
                snapshotRevision = counters.SnapshotRevision,
                shellPid = counters.ShellPid, shellCreationTime = counters.ShellBirth,
                officePid = counters.OfficePid, officeCreationTime = counters.OfficeBirth,
                originalFormHwnd = counters.Form, originalPanelHwnd = counters.Panel, originalChildHwnd = counters.Child,
                shellThreadId = counters.ShellThread, editorThreadId = counters.EditorThread, managedThreadId = counters.ManagedThread,
                preOwnerActivated = count[0], preOwnerAppActive = count[1], preOwnerAppInactive = count[2],
                activatedCount = count[3], appActiveCount = count[4], appInactiveCount = count[5],
                queueEntryCount = count[6], queueGuardCount = count[7], coreQueueCount = count[8],
                coreQueueTrueCount = count[9], coreQueueFalseCount = count[10],
                postAttemptCount = count[11], postReturnCount = count[12], callbackEntryCount = count[13], callbackExitCount = count[14],
                availabilityCount = count[15], pendingKnown = counters.PendingKnown, pending = counters.PendingValue,
                availabilityKnown = counters.AvailabilityKnown, availabilityValue = counters.AvailabilityValue,
                availabilityMaskKnown = counters.MaskKnown, availabilitySourceCode = counters.AvailabilitySource,
                evaluatedMask = counters.EvaluatedMask, trueMask = counters.TrueMask, firstRejectId = counters.FirstReject,
                evaluationComplete = counters.EvaluationComplete,
                postUncertain = count[11] == count[12] ? 0 : 1, callbackOutstanding = count[11] == count[14] ? 0 : 1
            }, counters.WorkerPid, counters.TraceId);
        }
        catch (Exception) { counters.UpdateFailed = 1; }
    }

    private void WriteInitialFocusStatus(InitialFocusCounters? counters)
    {
        try
        {
            if (!initialFocusStatusDiagnostics.Enabled || counters is null ||
                Environment.CurrentManagedThreadId != uiThreadId || counters.ManagedThread != uiThreadId ||
                !ReferenceEquals(initialFocusCounters, counters) || !ReferenceEquals(editorFocus, counters.Owner) ||
                counters.Generation != initialFocusOwnerGeneration || counters.IdentityKnown != 1 ||
                counters.OwnerChanged != 0 || counters.Retired != 0 || counters.DisposeReturned != 0 ||
                counters.UpdateFailed != 0 || counters.OverflowMask != 0 || counters.SnapshotRevision <= 0 ||
                counters.Form <= 0 || counters.Panel <= 0 || counters.Child <= 0 ||
                counters.Form == counters.Panel || counters.Form == counters.Child || counters.Panel == counters.Child ||
                counters.Form != editorFocusFormHwnd.ToInt64() || counters.Panel != editorFocusPanelHwnd.ToInt64() ||
                counters.WorkerPid is null || counters.TraceId is null) return;
            // Sample only the managed comparison after the existing status prefix.
            // This value never participates in a focus, queue, availability or counter decision.
            var activeFormIsThis = ReferenceEquals(ActiveForm, this) ? 1 : 0;
            initialFocusStatusDiagnostics.Write("status.completed", new
            {
                schemaVersion = 1, ownerGeneration = counters.Generation,
                prefixSnapshotRevision = counters.SnapshotRevision,
                originalFormHwnd = counters.Form, originalPanelHwnd = counters.Panel, originalChildHwnd = counters.Child,
                activeFormIsThis
            }, counters.WorkerPid, counters.TraceId);
        }
        catch (Exception) { /* Independent observations cannot change status or focus behavior. */ }
    }

    private void ReleaseEditorFocus()
    {
        var owned = editorFocus;
        var counters = InitialFocusCountersFor(owned);
        editorFocus = null; editorFocusFormHwnd = editorFocusPanelHwnd = 0;
        if (counters is not null) counters.Retired = 1;
        try
        {
            owned?.Dispose();
            if (counters is not null) counters.DisposeReturned = 1;
        }
        finally { WriteInitialFocusFinal(counters); }
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
