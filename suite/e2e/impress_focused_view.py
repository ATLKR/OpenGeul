"""Positive owned VCL focus, not a census or an OS-foreground/input permit.

LO 26.8.1.1 Window::HasFocus compares this with its process-global focus
window. The same peer's XAccessible is admitted only as the concrete Draw
document class, with a full reciprocal path to the original component.
getWindows enumerates native children internally before its returned-size cap.
"""
from __future__ import annotations
import copy
import json
import operator
import re
import uuid

CONTRACT='impress-focused-view-edit-context-v2'
SCOPE='positive-focused-semantic-view'
IMPLEMENTATION='AccessibleDrawDocumentView'
SERVICE='com.sun.star.drawing.AccessibleDrawDocumentView'
LIMITS=dict(visits=256,depth=8,children=64)
FACTS={'hasFocus','peerPathStable','properComponentChild','properContainerChild',
    'distinctComponentPeer','distinctContainerPeer','sameAccessible','accessiblePathStable'}
REASONS={'null-peer','focus-api','children-api','null-children','depth','children-cap'}


def _path(value,maximum=8):
    assert type(value) is list and len(value)<=maximum
    assert all(type(index) is int and 0<=index<64 for index in value)
    return value


def _services(value):
    assert type(value) in (tuple,list) and 1<=len(value)<=64
    assert all(type(name) is str and 0<len(name)<=256 for name in value)
    assert SERVICE in value, 'Focused peer has the wrong document service'
    return list(value)


def require_focus_binding(binding,*,previous=None):
    """Pure replay; the external caller, never this receipt, selects v2."""
    from calc_pending_input import _visible
    assert 'documentIdentity' in binding
    focus=binding.get('focusBinding')
    assert type(focus) is dict and set(focus)=={'contract','scope','peerIdentity','peerPath','search','before','after'}
    assert focus['contract']==CONTRACT and focus['scope']==SCOPE
    assert type(focus['peerIdentity']) is str and re.fullmatch('[a-f0-9]{32}',focus['peerIdentity'])
    path=_path(focus['peerPath']);assert path, 'Focused peer must be a proper component descendant'
    for phase in ('before','after'):
        checks=focus[phase]
        assert type(checks) is dict and set(checks)==FACTS|{'role','stateBits','implementationName','serviceNames'}
        assert all(checks[name] is True for name in FACTS)
        assert type(checks['role']) is int and checks['role']==83
        state=checks['stateBits'];assert type(state) is int and 0<=state<2**63 and _visible(state)
        assert checks['implementationName']==IMPLEMENTATION
        assert type(checks['serviceNames']) is list;_services(checks['serviceNames'])
    assert focus['before']==focus['after'], 'Focused document class, state or service changed'
    search=focus['search']
    assert type(search) is dict and set(search)=={'visitedCount','limits','unknownBranches','unvisitedBranchCount','censusComplete','stop'}
    assert type(search['visitedCount']) is int and len(path)+1<=search['visitedCount']<=256
    assert type(search['limits']) is dict and set(search['limits'])==set(LIMITS)
    assert all(type(search['limits'][key]) is int and search['limits'][key]==want for key,want in LIMITS.items())
    assert search['censusComplete'] is False and search['stop']=='positive-global-focus'
    assert type(search['unvisitedBranchCount']) is int and 0<=search['unvisitedBranchCount']<=16384
    unknown=search['unknownBranches'];assert type(unknown) is list and len(unknown)<=search['visitedCount']
    paths=[]
    for row in unknown:
        assert type(row) is dict and set(row) in ({'path','reasons'},{'path','reasons','returnedChildren'})
        other=_path(row['path'],9);assert other not in paths and other!=path;paths.append(other)
        reasons=row['reasons'];assert type(reasons) is list and 1<=len(reasons)<=2
        assert all(type(reason) is str and reason in REASONS for reason in reasons) and len(set(reasons))==len(reasons)
        if 'children-cap' in reasons:
            assert type(row.get('returnedChildren')) is int and 65<=row['returnedChildren']<=65535
        else:assert 'returnedChildren' not in row
        if 'depth' in reasons:assert len(other)==9
        if any(reason!='focus-api' for reason in reasons):
            assert path[:len(other)]!=other, 'Selected focus lies below an unavailable branch'
    assert len(json.dumps(focus,allow_nan=False).encode('utf-8'))<=32768
    if previous is not None:
        assert focus==previous.get('focusBinding'), 'Retained focused view binding changed'
    return focus


class FocusedViewReader:
    def __init__(self,owner):
        self.owner=owner;self.peer=self.peer_nodes=self.document=self.document_nodes=None
        self.peer_path=self.document_path=None;self.identity=uuid.uuid4().hex
        self.search=dict(visitedCount=0,limits=dict(LIMITS),unknownBranches=[],
            unvisitedBranchCount=0,censusComplete=False,stop='not-started')
        self.stage='not-started'

    def _equal(self,left,right):
        value=self.owner.call(operator.eq,left,right)
        assert type(value) is bool, 'UNO identity comparison is not an exact boolean'
        return value

    def _method(self,peer,name):
        value=self.owner.call(getattr,peer,name,None)
        assert value is None or callable(value), 'Native peer API is not callable'
        return value

    def _unknown(self,path,reason,**extra):
        rows=self.search['unknownBranches']
        row=next((row for row in rows if row['path']==list(path)),None)
        if row is None:row=dict(path=list(path),reasons=[]);rows.append(row)
        row['reasons'].append(reason);row.update(extra)

    def _children(self,peer):
        method=self._method(peer,'getWindows')
        assert method is not None, 'Retained native peer path lost its container API'
        children=self.owner.call(method)
        assert type(children) in (list,tuple) and len(children)<=64, 'Retained native peer child bound changed'
        return children

    def _owned(self):
        owner=self.owner;checks={}
        for key,value in (
            ('distinctComponentPeer',not self._equal(self.peer,owner.component_peer)),
            ('distinctContainerPeer',not self._equal(self.peer,owner.peer)),
            ('properComponentChild',owner.call(owner.component_peer.isChild,self.peer)),
            ('properContainerChild',owner.call(owner.peer.isChild,self.peer))):
            assert value is True, 'Focused peer is outside its proper original owner: '+key
            checks[key]=value
        return checks

    def _lookup(self):
        owner=self.owner;pending=[(owner.component_peer,(),[owner.component_peer])];seen=[]
        self.search['stop']='no-positive-focus'
        while pending and self.search['visitedCount']<256:
            peer,path,nodes=pending.pop();self.search['visitedCount']+=1
            self.stage='peer-candidate'
            if len(path)>8:self._unknown(path,'depth');continue
            if peer is None:self._unknown(path,'null-peer');continue
            assert not any(self._equal(peer,other) for other in seen), 'Native peer alias or cycle'
            seen.append(peer)
            focus=self._method(peer,'hasFocus')
            if focus is None:self._unknown(path,'focus-api')
            else:
                self.stage='positive-focus-getter';focused=owner.call(focus)
                assert type(focused) is bool, 'Native focus is not an exact boolean'
                if focused:
                    self.peer,self.peer_path,self.peer_nodes=peer,list(path),nodes
                    self._owned()
                    self.search.update(stop='positive-global-focus',unvisitedBranchCount=len(pending))
                    return
            method=self._method(peer,'getWindows')
            if method is None:self._unknown(path,'children-api');continue
            self.stage='native-children-getter';children=owner.call(method)
            if children is None:self._unknown(path,'null-children');continue
            assert type(children) in (list,tuple), 'Malformed native peer children'
            if len(children)>64:
                assert len(children)<=65535
                self._unknown(path,'children-cap',returnedChildren=len(children));continue
            # Returned aliases are already known, even if positive focus would
            # stop before a later sibling or queued branch is visited.
            known=seen+[node for node,_,_ in pending if node is not None]
            for child in children:
                if child is None:continue
                assert not any(self._equal(child,node) for node in known), 'Native peer alias or cycle'
                known.append(child)
            for index in range(len(children)-1,-1,-1):
                child=children[index];pending.append((child,path+(index,),nodes+[child]))
        self.search['unvisitedBranchCount']=len(pending)
        if pending:self.search['stop']='visit-bound-no-positive-focus'
        raise AssertionError('No positively focused owned Impress document within fixed peer bound')

    def _native_path(self):
        owner=self.owner;current=owner.component_peer
        assert self._equal(current,self.peer_nodes[0])
        for depth,index in enumerate(self.peer_path):
            children=self._children(current);assert index<len(children)
            current=children[index]
            assert current is not None and self._equal(current,self.peer_nodes[depth+1]), 'Retained focused peer path changed'
        assert self._equal(current,self.peer)
        return True

    def _accessible_path(self,document):
        owner=self.owner;nodes=[document];indices=[];current=document
        while not self._equal(current,owner.root):
            assert len(indices)<8, 'Focused document full accessible path exceeded fixed depth'
            context=owner.call(current.getAccessibleContext)
            parent=owner.call(context.getAccessibleParent);assert parent is not None
            assert not any(self._equal(parent,node) for node in nodes), 'Accessible parent alias or cycle'
            index=owner.call(context.getAccessibleIndexInParent)
            assert type(index) is int and 0<=index<64
            parent_context=owner.call(parent.getAccessibleContext)
            count=owner.call(parent_context.getAccessibleChildCount)
            assert type(count) is int and 0<=count<=64 and index<count
            assert self._equal(owner.call(parent_context.getAccessibleChild,index),current), 'Accessible parent/index identity changed'
            nodes.append(parent);indices.append(index);current=parent
        return list(reversed(indices)),list(reversed(nodes))

    def _phase(self):
        owner=self.owner;owner._peer();checks=self._owned()
        checks['peerPathStable']=self._native_path()
        checks['sameAccessible']=self._equal(owner.call(self.peer.getProperty,'XAccessible'),self.document)
        assert checks['sameAccessible'], 'Focused peer accessible changed'
        path,nodes=self._accessible_path(self.document)
        assert path==self.document_path and len(nodes)==len(self.document_nodes)
        assert all(self._equal(node,retained) for node,retained in zip(nodes,self.document_nodes)), 'Focused accessible path changed'
        checks['accessiblePathStable']=True
        context=owner.call(self.document.getAccessibleContext)
        role=owner.call(context.getAccessibleRole);state=owner.call(context.getAccessibleStateSet)
        from calc_pending_input import _visible
        assert type(role) is int and role==83, 'Focused peer is not the presentation document'
        assert type(state) is int and 0<=state<2**63 and _visible(state), 'Focused document is not visible'
        name=owner.call(self.document.getImplementationName)
        assert type(name) is str and name==IMPLEMENTATION, 'Focused peer has the wrong document class'
        services=_services(owner.call(self.document.getSupportedServiceNames))
        focused=owner.call(self.peer.hasFocus);assert focused is True, 'Retained document lost positive VCL focus'
        checks.update(hasFocus=focused,role=role,stateBits=state,implementationName=name,serviceNames=services)
        return checks

    def read(self):
        owner=self.owner
        try:
            owner._peer()
            if self.peer is None:
                self._lookup();self.stage='same-peer-accessible'
                document=owner.call(self.peer.getProperty,'XAccessible');assert document is not None
                path,nodes=self._accessible_path(document)
                self.document,self.document_path,self.document_nodes=document,path,nodes
                owner.document,owner.document_path,owner.document_nodes=document,path,nodes
            self.stage='focused-view-before';before=self._phase()
            self.stage='selected-document-editing-context';result=owner._impress()
            self.stage='focused-view-after';after=self._phase()
            result['accessibleBinding']['focusBinding']=dict(contract=CONTRACT,scope=SCOPE,peerIdentity=self.identity,
                peerPath=list(self.peer_path),search=copy.deepcopy(self.search),before=before,after=after)
            require_focus_binding(result['accessibleBinding'])
            return result
        except BaseException as exc:
            try:
                diagnostic=dict(contract=CONTRACT,scope=SCOPE,stage=self.stage,childHwnd=owner.child_hwnd,
                    peerPath=self.peer_path,documentPath=self.document_path,search=copy.deepcopy(self.search),qualification=False)
                assert len(json.dumps(diagnostic,allow_nan=False).encode('utf-8'))<=32768
                exc.impress_focused_view_diagnostic=diagnostic
            except BaseException:pass
            raise

    def release(self):
        self.peer=self.peer_nodes=self.document=self.document_nodes=self.owner=None
        self.peer_path=self.document_path=None
