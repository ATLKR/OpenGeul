"""Finite metadata from an already verified owned startup-error dialog.

The retained Popen HANDLE proves the original shell is alive. No process creation
timestamp, document state, or error text is collected or claimed.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os

PROPERTY = 'OpenGeul.Office.StartupDiagnosticV1'
OPT_IN = 'OPENGEUL_SUITE_NUMERIC_NOTICE'
REASONS = frozenset((*range(28), *range(32,39)))
NATIVE_CODES = frozenset((0,2,3,5,8,14,32,87,126,127,193,216,740))
_CONTEXT_KEYS = ('GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','RUNNER_ARCH','OPENGEUL_SUITE_NOTICE_SCOPE')
_SEAL = object()


def decode_property(value):
    if type(value) is not int or not 0<value<2**63 or value>>56!=1:
        return None
    phase,reason,native=(value>>48)&255,(value>>32)&65535,value&0xffffffff
    if phase not in (1,2,3) or reason not in REASONS or native not in NATIVE_CODES:
        return None
    return [phase,reason,native]


class _ObservedStartup:
    __slots__ = ('seal','shell_pid','startup','context')
    def __init__(self,shell_pid,startup,environ):
        self.seal,self.shell_pid,self.startup=_SEAL,shell_pid,tuple(startup)
        self.context=tuple(environ.get(key) for key in _CONTEXT_KEYS)


def _native_wait_zero():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    wait=kernel.WaitForSingleObject
    wait.argtypes=(wintypes.HANDLE,wintypes.DWORD)
    wait.restype=wintypes.DWORD
    return lambda handle:wait(handle,0)


def _owned(api,pid,dialog,owner):
    return (api.user.IsWindow(dialog) and api.user.IsWindow(owner)
        and api.pid(dialog)==pid and api.pid(owner)==pid
        and api.user.GetWindow(dialog,4)==owner
        and api.user.GetAncestor(dialog,2)==dialog
        and api.user.GetAncestor(owner,2)==owner)


def receive(api,process,dialog,owner,*,wait_zero=None,environ=None):
    """Return a private receipt or unknown; never alter the primary failure."""
    environ=os.environ if environ is None else environ
    if environ.get(OPT_IN)!='1':return None
    try:
        pid=process.pid
        handle=getattr(process,'_handle',None)
        if (type(pid) is not int or not 0<pid<=0xffffffff or not dialog or not owner
                or not _owned(api,pid,dialog,owner)):return None
        word=api.user.GetPropW(owner,PROPERTY)
        startup=decode_property(word)
        # An absent/old sender never loads kernel32 or inspects a new handle.
        if startup is None:return None
        if not isinstance(handle,int) or isinstance(handle,bool) or not 0<int(handle)<2**64:return None
        wait=wait_zero if wait_zero is not None else _native_wait_zero()
        if wait(handle)!=258 or not _owned(api,pid,dialog,owner):return None
        if api.user.GetPropW(owner,PROPERTY)!=word:return None
        if wait(handle)!=258 or not _owned(api,pid,dialog,owner):return None
        if process.pid!=pid or process._handle is not handle:return None
        return _ObservedStartup(pid,startup,environ)
    except Exception:
        return None


def attach(exc,receipt):
    if isinstance(exc,BaseException) and type(receipt) is _ObservedStartup and receipt.seal is _SEAL:
        vars(exc)['_openg_startup_observation']=receipt


def project_exception(exc,*,environ=None):
    receipt=vars(exc).get('_openg_startup_observation') if isinstance(exc,BaseException) else None
    if type(receipt) is not _ObservedStartup or receipt.seal is not _SEAL:return None
    if environ is not None and receipt.context!=tuple(environ.get(key) for key in _CONTEXT_KEYS):return None
    return dict(shellPid=receipt.shell_pid,startup=list(receipt.startup))
