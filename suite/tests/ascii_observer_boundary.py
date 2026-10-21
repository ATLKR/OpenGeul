"""Test-only observer boundary for existing input/model routing fixtures.

Real queue policy, native transport/identity and cleanup have independent tests.
This seam observes sequencing without compiling or injecting a Windows hook.
"""
class AsciiObserverBoundary:
    def __init__(self, api, process, binding, prepared, record, deadline, **kwargs):
        self.receipt = dict(success=False, semanticInsertionProved=False, actions=[])
        record.setdefault('asciiMessageObservers', []).append(self.receipt)
        self.finished = False
    def __enter__(self): return self
    def __exit__(self, typ, exc, tb):
        self.receipt['success'] = exc is None and self.finished
        return False
    def arm(self, action): self.receipt['actions'].append(action)
    def await_progress(self, action):
        return dict(queueConsumed=True,semanticInsertionProved=False,finalSequence=action['index']+1)
    def finish(self, count):
        assert len(self.receipt['actions']) == count
        self.finished = True
