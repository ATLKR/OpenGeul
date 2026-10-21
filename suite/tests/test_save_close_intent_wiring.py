"""Source guards for the WinForms binding; executable policy behavior is in C#."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / 'shell/OfficeDocumentForm.cs'


def method(source, signature):
    start = source.index(signature)
    begin = source.index('{', start)
    depth = 1
    for end in range(begin + 1, len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if depth == 0:
            return source[begin + 1:end]
    raise AssertionError('C# method body did not end')


class SaveCloseIntentWiringTests(unittest.TestCase):
    def setUp(self):
        self.source = FORM.read_text(encoding='utf-8')

    def test_the_actual_save_wraps_the_captured_worker_and_form_in_the_core_policy(self):
        body = method(self.source, 'private async Task<bool> SaveDocumentAsync(')
        self.assertIn('var saveWorker = worker;', body)
        self.assertIn('var saveHwnd = IsHandleCreated ? Handle : 0;', body)
        self.assertIn('saveCloseIntent.RunAsync(saveWorker, closing,', body)
        self.assertIn('() => SaveDocumentCoreAsync(saveAs, commandSequence, saveWorker)', body)
        self.assertIn('() => worker,', body)
        self.assertIn('await RequestCloseAsync();', body)
        self.assertLess(body.index('if (!attached || worker is null || loading || busy)'),
                        body.index('saveCloseIntent.RunAsync('))

    def test_the_drain_checks_the_same_live_original_form_without_creating_a_handle(self):
        body = method(self.source, 'private async Task<bool> SaveDocumentAsync(')
        for gate in ('Environment.CurrentManagedThreadId == uiThreadId', 'saveHwnd != 0',
                     '!IsDisposed', '!Disposing', 'IsHandleCreated', 'Handle == saveHwnd',
                     'attached', '!loading', '!busy', '!closing', '!closeApproved'):
            self.assertIn(gate, body)
        condition = body[body.index('() => Environment.CurrentManagedThreadId'):]
        self.assertLess(condition.index('!IsDisposed'), condition.index('Handle == saveHwnd'))
        self.assertLess(condition.index('!Disposing'), condition.index('Handle == saveHwnd'))
        self.assertLess(condition.index('IsHandleCreated'), condition.index('Handle == saveHwnd'))
        self.assertNotIn('statusBusy', condition)
        self.assertNotIn('resizeBusy', condition)

    def test_loading_and_close_recursion_are_guarded_before_a_save_close_can_queue(self):
        body = method(self.source, 'internal async Task<bool> RequestCloseAsync(')
        request = body.index('saveCloseIntent.RequestClose(worker)')
        for gate in ('if (IsDisposed || closeApproved)', 'if (closing)', 'if (loading)', 'if (Disposing)'):
            self.assertLess(body.index(gate), request)
        self.assertIn('if (busy)', body)
        self.assertIn('Environment.CurrentManagedThreadId == uiThreadId', body)
        self.assertIn('worker is not null', body)
        self.assertIn('DocumentClose.TryAsync(this, () => Task.FromResult(ChooseClose()), () => SaveDocumentAsync(false))', body)

    def test_save_operation_clears_busy_before_policy_can_drain(self):
        body = method(self.source, 'private async Task<bool> SaveDocumentCoreAsync(')
        self.assertIn('await saveWorker.SendAsync("save", request', body)
        self.assertIn('finally { busy = false; EnableSave(attached && !closing); }', body)
        self.assertNotIn('RequestCloseAsync', body)
        self.assertNotIn('saveCloseIntent.RequestClose', body)

    def test_worker_release_and_form_disposal_invalidate_pending_operation_authority(self):
        release = method(self.source, 'private async Task ReleaseWorkerAsync(')
        self.assertLess(release.index('saveCloseIntent.Invalidate();'), release.index('worker = null;'))
        disposal = method(self.source, 'protected override void Dispose(')
        self.assertLess(disposal.index('saveCloseIntent.Invalidate();'), disposal.index('base.Dispose(disposing);'))


if __name__ == '__main__':
    unittest.main()
