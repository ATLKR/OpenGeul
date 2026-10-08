"""Exact semantic action identity for English hosted-runner print previews."""
SYSTEM_NAMES = frozenset({
    'Print using system dialog… (Ctrl+Shift+P)',
    'Print using system dialog... (Ctrl+Shift+P)',
})

def system_link(nodes: list[dict], owner_pids: set[int]) -> int | None:
    """Return one exact owned action; visibility is a separate click-readiness gate."""
    matches = [i for i,node in enumerate(nodes)
               if node.get('name') in SYSTEM_NAMES and node.get('type') in ('Button','Hyperlink')
               and node.get('enabled') is True and node.get('pid') in owner_pids]
    if len(matches) > 1:
        raise ValueError('Ambiguous system-print action; refusing to click')
    return matches[0] if matches else None
