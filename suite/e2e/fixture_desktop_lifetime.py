"""Explicit service lifetime for run_case's private generated fixtures only.

XDesktop's ordinary termination veto owns process lifetime after frames may
close. It is not a document-close veto or a claim about a prior bridge failure.
Callbacks retain bounded local facts; they perform no clock, remote or I/O calls.
"""
import os
from pathlib import Path


def _listener(owner):
    import unohelper
    from com.sun.star.frame import XTerminateListener, TerminationVetoException

    class Listener(unohelper.Base, XTerminateListener):
        def queryTermination(self, event):
            owner._callback('queryTermination')
            if owner.active:
                raise TerminationVetoException('Owned generated fixture is still active', self)
        def notifyTermination(self, event):owner._callback('notifyTermination')
        def disposing(self, event):owner._callback('disposing')
    return Listener()


class FixtureDesktopLease:
    def __init__(self, desktop, diagnostics):
        self.desktop,self.diagnostics=desktop,diagnostics
        self.active=True
        self.callback_fault=self.unexpected_termination=False
        self.receipt=dict(schemaVersion=1,kind='owned-generated-fixture-desktop-lifetime',
            scope='explicit-run-case-fixture',registration='not-attempted',removal='not-attempted',
            active=True,events=[],omittedEvents=0,unexpectedTermination=False,callbackFault=False)
        self.listener=_listener(self)

    def _callback(self, event):
        if self.active and event in ('notifyTermination','disposing'):
            self.unexpected_termination=True
        try:
            if len(self.receipt['events'])<64:
                self.receipt['events'].append(dict(event=event,active=self.active))
            else:self.receipt['omittedEvents']=min(64,self.receipt['omittedEvents']+1)
            self.receipt['unexpectedTermination']=self.unexpected_termination
            self.receipt['callbackFault']=self.callback_fault
        except BaseException:
            self.callback_fault=True
            try:self.receipt['callbackFault']=True
            except BaseException:pass

    def _healthy(self):
        assert not self.callback_fault, 'Fixture lifetime callback recording failed'
        assert not self.unexpected_termination, 'Owned fixture Desktop unexpectedly terminated'
        assert self.receipt['registration']=='returned', 'Fixture lifetime registration did not return'
        assert not self.receipt['omittedEvents'], 'Fixture lifetime callbacks exceeded fixed bound'
        assert self.receipt['unexpectedTermination'] is False, 'Owned fixture Desktop unexpectedly terminated'

    def register(self):
        assert self.receipt['registration']=='not-attempted'
        self.receipt['registration']='attempted'
        try:self.diagnostics.call('fixture.desktop.listener.add',lambda:self.desktop.addTerminateListener(self.listener))
        except BaseException:
            self.receipt['registration']='raised';raise
        self.receipt['registration']='returned'
        self.require_active()

    def require_active(self):
        self._healthy()
        assert self.active and self.receipt['removal']=='not-attempted', 'Fixture lifetime was released early'

    def release(self):
        assert self.receipt['removal']=='not-attempted', 'Fixture listener removal cannot be retried'
        assert self.receipt['registration']!='not-attempted'
        self.active=False;self.receipt['active']=False
        self.receipt['removal']='attempted'
        try:self.diagnostics.call('fixture.desktop.listener.remove',lambda:self.desktop.removeTerminateListener(self.listener))
        except BaseException:
            self.receipt['removal']='raised';raise
        self.receipt['removal']='returned'
        self.listener=None
        self._healthy()


def require_fixture_members(rows, expected_image):
    """Only run_case opts in to this NEW early retained native observation."""
    assert type(rows) is list and 1<=len(rows)<=128, 'Missing bounded early fixture members'
    image=lambda value:os.path.normcase(str(Path(value).resolve()))
    expected=image(expected_image)
    for row in rows:
        assert not row.get('error') and all(type(row.get(key)) is int and row[key]>0
            for key in ('pid','creationTime','handleValue')), 'Incomplete early fixture generation'
        assert type(row.get('image')) is str and type(row.get('alive')) is bool
    assert any(row['alive'] is True and image(row['image'])==expected for row in rows), \
        'Expected owned engine was not retained alive before fixture load'
