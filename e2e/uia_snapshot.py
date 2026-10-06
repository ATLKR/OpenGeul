"""Bounded read-only handling of a disappearing native accessibility snapshot.

pywinauto 0.6.9 can observe an element's control_type and then lose that
virtualized element before constructing its wrapper, producing KeyError(None).
Discard the incomplete snapshot and read the same owned root again. This helper
never dispatches input or wraps a click, Select, Expand, Invoke, or print action.
"""
from __future__ import annotations
import time


def snapshot_descendants(root, **filters):
    deadline = time.monotonic() + 5.0
    last_error = None
    unavailable = 0
    while time.monotonic() < deadline:
        try:
            result = root.descendants(**filters)
        except KeyError as error:
            if error.args != (None,):
                raise
            last_error = error
            unavailable += 1
            time.sleep(.15)
        else:
            if unavailable:
                print(f'UIA read: discarded {unavailable} unavailable snapshot(s); no input repeated.', flush=True)
            return result
    raise AssertionError('Native accessibility snapshot stayed unavailable for five seconds') from last_error
