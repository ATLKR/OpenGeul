"""Test-only observer boundary for existing input/model routing fixtures.

Real queue policy, native transport/identity and cleanup have independent tests.
This seam observes sequencing without compiling or injecting a Windows hook.
"""
class AsciiObserverBoundary:
    def __init__(self, api, process, binding, prepared, record, deadline, **kwargs):
        self.receipt = dict(success=False, semanticInsertionProved=False, actions=[])
        record.setdefault('asciiMessageObservers', []).append(self.receipt)
        self.finished = False
        self.deadline = deadline
    def __enter__(self):
        # This substitutes the WHOLE observer for input/model caller tests.
        # The mandatory real queue policy and native transaction are exercised
        # elsewhere; never fabricate a native ready sample from this stand-in.
        self.receipt['initialQueueReadiness'] = dict(kind='test-only-initial-queue-phase',
            observedNative=False, deadline=self.deadline)
        return self
    def __exit__(self, typ, exc, tb):
        self.receipt['success'] = exc is None and self.finished
        return False
    def arm(self, action):
        assert 'initialQueueReadiness' in self.receipt, 'Test observer initial phase missing'
        self.receipt['actions'].append(action)
    def await_progress(self, action):
        return dict(queueConsumed=True,semanticInsertionProved=False,finalSequence=action['index']+1)
    def finish(self, count):
        assert len(self.receipt['actions']) == count
        self.finished = True
