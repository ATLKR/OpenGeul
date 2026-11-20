"""Finite classes and PID-value equality from the current failed guard only.

The vector is [beforeClass, afterClass, samePidValue]. None is unobserved;
class 0 is an observed, unrecognized (including empty) string. These exact
class literals are categories, not window identities. PID-value equality is
not process identity, lifetime, generation, or foreground-causation proof.
No window, process, filesystem, clock, or input API is called here.
"""
from __future__ import annotations

if __package__:
    from . import focus_summary
else:
    import focus_summary

# Append-only wire codes. Do not serialize or parse arbitrary class suffixes.
CLASS_CODES={name:index for index,name in enumerate((
    'ConsoleWindowClass','CASCADIA_HOSTING_WINDOW_CLASS','#32770','#32768',
    'IME','MSCTFIME UI','CicMarshalWndClass','Progman','WorkerW','Shell_TrayWnd',
    'Shell_SecondaryTrayWnd','ApplicationFrameWindow','Windows.UI.Core.CoreWindow',
    'CabinetWClass','ExploreWClass','tooltips_class32','Notepad','SALFRAME','SALSUBFRAME'),1)}
MAX_CLASS_CODE=19


def valid(value,focus):
    """Validate a closed vector against the already validated focus relations."""
    if type(value) is not list or len(value)!=3 or type(focus) is not list or len(focus)!=5:return False
    if any(v is not None and (type(v) is not int or not 0<=v<=MAX_CLASS_CODE) for v in value[:2]):return False
    same=value[2]
    if any(relation in (0,1) for relation in focus[:2]):return same is None
    if type(same) is not int or same not in (0,1):return False
    before,after=focus[:2]
    if before in (2,3) and after in (2,3):return same==int(before==after)
    if (before==5 and after in (2,3,4)) or (after==5 and before in (2,3,4)):return same==0
    return True


def project(record):
    """Reuse the original guard/generation/deadline admission; never observe anew."""
    try:
        if (type(record) is not dict or record.get('module')!='calc'
                or record.get('kind')!='calc-save-dispatch-diagnostic' or record.get('architecture')!='arm64'):return None
        focus=focus_summary.project(record)
        if focus is None:return None
        # PRE/POST may also contain old successful scopes. Require the existing
        # source-frame chain proving this is the current shared-guard failure.
        focus_summary._current_guard_failure(record)
        scope=record['imeKeyboardSession']['lastGuardObservation']['scope']
        classes=[];pids=[]
        for edge in ('before','after'):
            foreground=scope[edge]['foreground']
            if 'className' not in foreground:classes.append(None)
            else:
                name=foreground['className']
                if type(name) is not str or len(name)>255:return None
                classes.append(CLASS_CODES.get(name,0))
            pid=foreground['pid']
            pids.append(pid if type(pid) is int and 0<pid<=0xffffffff else None)
        result=classes+[int(pids[0]==pids[1]) if all(pid is not None for pid in pids) else None]
        return result if valid(result,focus) else None
    except (KeyError,ValueError,TypeError,OverflowError):return None
