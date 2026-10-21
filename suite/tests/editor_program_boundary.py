"""Native session seam for older GUI/model routing tests.

The real session policy, raw buffers and guards are tested separately. This
boundary only observes requested presets; original model.complete still runs.
"""
LABELS = {'CTRL_F6':'^{F6}', 'CTRL_HOME':'^{HOME}', 'F2':'{F2}', 'CTRL_END':'^{END}',
          'TAB':'{TAB}', 'ENTER':'{ENTER}', 'CTRL_S':'^s', 'CTRL_1':'^1'}


class EditorProgramBoundary:
    def __init__(self, api, process, attachment, program, record, deadline, *, marker=None, inject=lambda key,**kw:None):
        self.deadline, self.record, self.inject = deadline, record, inject
        self.record.setdefault('editorFocusReadiness', {'ready':True})
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def press(self, preset): self.inject(LABELS[preset],pause=.1)
    def editor_ready(self, evidence): pass
    def typed(self, evidence): pass
    def join_model(self, context, plan):
        if not isinstance(getattr(context, 'deadline', None), (int, float)):
            context.deadline=getattr(plan, 'deadline', self.deadline)
        self.deadline=context.deadline
    def complete_model(self, context, plan): return context.complete(plan)
    def save_phase(self, deadline): self.deadline=deadline


def editor_program_factory(inject):
    return lambda *args, **kwargs: EditorProgramBoundary(*args, **kwargs, inject=inject)
