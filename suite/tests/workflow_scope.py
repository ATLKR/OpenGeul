"""Pure-text scope for the fixed Office Suite workflow's job mapping.

This is a narrow reader for the reviewed block layout, not a YAML parser.
Unsupported mapping syntax fails closed. Global fields remain available while
normal Suite readers never see the dedicated Writer job's steps.
"""
import re

_JOBS=re.compile(r'jobs:[ \t]*(?:#.*)?')
_JOB=re.compile(r'''  (?:([A-Za-z_][A-Za-z0-9_-]*)|'([^']+)'|"([^"]+)"):[ \t]*(?:#.*)?''')


def suite_workflow_sections(source):
    """Return original global header and normal block, by job name.

    Only the legacy normal job or exactly normal+Writer jobs are permitted.
    No unrecognized or duplicate job can disappear when selecting a block.
    Interior and EOF bytes are preserved. At most one blank inter-job
    separator is excluded when another job follows; legacy EOF is untouched.
    """
    if type(source) is not str:raise ValueError('Office Suite workflow text required')
    lines=source.splitlines(keepends=True)
    roots=[i for i,line in enumerate(lines) if _JOBS.fullmatch(line.rstrip('\r\n'))]
    if len(roots)!=1:raise ValueError('One fixed Office Suite jobs mapping required')
    root=roots[0];jobs=[]
    for i,line in enumerate(lines[root+1:],root+1):
        text=line.rstrip('\r\n')
        if not text.strip() or text.lstrip().startswith('#'):continue
        if not text.startswith('  ') or text.startswith('\t'):
            raise ValueError('Unsupported Office Suite mapping layout')
        if len(text)>2 and text[2] not in (' ','\t'):
            match=_JOB.fullmatch(text)
            if match is None:raise ValueError('Unsupported Office Suite job mapping')
            jobs.append((next(value for value in match.groups() if value is not None),i))
    names=[name for name,_ in jobs]
    if (len(set(names))!=len(names) or set(names) not in
            ({'windows-suite'},{'windows-suite','writer-server-observer'})):
        raise ValueError('Unknown, duplicate or missing Office Suite job')
    at=names.index('windows-suite');start=jobs[at][1];end=jobs[at+1][1] if at+1<len(jobs) else len(lines)
    header=''.join(lines[:root])
    block=lines[start:end]
    if end<len(lines) and block and block[-1].strip()=='' and block[-1].strip('\r\n')=='':block=block[:-1]
    normal=''.join(block)
    return header,normal


def normal_suite_source(source):
    header,normal=suite_workflow_sections(source)
    marker=source[len(header):].splitlines(keepends=True)[0]
    return header+marker+normal


def original_acceptance_source(source):
    """Test-only view of original gates after the exact reviewed probe tail.

    Keep the full normal reader unchanged. Only this sealed observation tail
    may disappear, and the independent original-job oracle must still match.
    """
    import hashlib
    from suite.tests.reviewed_normal_workflow import (
        BUNDLED_CLANG_PROBE_START, _without_bundled_clang_probe, _without_engine_summary_artifacts,
        original_normal_oracle_text)
    header,normal=suite_workflow_sections(source)
    if normal.count(BUNDLED_CLANG_PROBE_START)!=1:
        raise ValueError('Exactly one reviewed observation tail is required')
    original=_without_engine_summary_artifacts(_without_bundled_clang_probe(normal))
    if hashlib.sha256(original_normal_oracle_text(original).encode('utf-8')).hexdigest()!=('af42f45cd2930ffa6d7f322a7b1e561bd199c1c8374897f33598785d19f5566f'):
        raise ValueError('Original acceptance job differs from the independent oracle')
    marker=source[len(header):].splitlines(keepends=True)[0]
    return header+marker+original
