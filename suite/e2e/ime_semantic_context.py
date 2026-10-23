"""Read-only, original-frame editing contexts; no keyboard or UNO setters.

These getters describe the sampled GUI insertion destination. Native insertion
and queue receipts never replace exact edit-buffer and saved/model effects.
"""
from __future__ import annotations
import base64
import copy
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
import zlib

MAX_TEXT=1024*1024
SOURCE='libreoffice-26.8.1.1'
PREFIXES={module:' ime-opengeul-'+module+':' for module in ('writer','calc','impress')}
GETTERS={module:module+('-a1' if module=='calc' else '')+'-active-edit-context-v1' for module in PREFIXES}
SERVICES=dict(writer='com.sun.star.text.TextDocument',calc='com.sun.star.sheet.SpreadsheetDocument',
              impress='com.sun.star.presentation.PresentationDocument')
CONTAINER_ROLES={21,40,49,51,56,66,67}
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
P='http://schemas.openxmlformats.org/presentationml/2006/main'


def _time(value):
    assert type(value) in (int,float) and math.isfinite(value) and value>=0
    return float(value)


def _integer(value, minimum=0):
    assert type(value) is int and minimum<=value<=MAX_TEXT, 'Invalid supported edit offset/count'
    return value


def _text(value):
    assert isinstance(value,str) and len(value.encode('utf-8'))<=MAX_TEXT
    return value


def _utf16(value):return len(_text(value).encode('utf-16-le'))//2


def fixture_baseline(module,data):
    """Read independent prelaunch bytes, never a live/model-supplied baseline."""
    assert module in PREFIXES and isinstance(data,bytes) and 0<len(data)<=16*1024*1024
    value=dict(module=module,sourceSha256=hashlib.sha256(data).hexdigest())
    if module=='calc':
        from calc_model_barrier import baseline_from_ooxml
        cells=baseline_from_ooxml(data);text=cells['a1Text']
        assert not any(ch in text for ch in '\r\n\t'), 'Fixed A1 fixture must be one plain paragraph'
        return dict(value,text=_text(text),cells=cells,plainParagraph=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names=archive.namelist();assert len(names)==len(set(names))
        assert all(not n.startswith(('/','\\')) and '\\' not in n and '..' not in PurePosixPath(n).parts for n in names)
        def xml(name):
            assert archive.getinfo(name).file_size<=2*MAX_TEXT
            raw=archive.read(name);assert b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper()
            return ET.fromstring(raw)
        if module=='writer':
            root=xml('word/document.xml');body=root.find('{'+W+'}body');assert body is not None
            assert not any(list(body.iter('{'+W+'}'+name)) for name in ('fldSimple','fldChar','instrText','numPr'))
            tokens={W+'}t':None,W+'}br':'\n',W+'}cr':'\n',W+'}tab':'\t'}
            paragraphs=[''.join((node.text or '') if tokens[node.tag[1:]] is None else tokens[node.tag[1:]]
                for node in paragraph.iter() if node.tag[1:] in tokens) for paragraph in body.iter('{'+W+'}p')]
            assert paragraphs
            return dict(value,text=_text('\n'.join(paragraphs)),paragraphCount=len(paragraphs))
        assert [name for name in names if re.fullmatch(r'ppt/slides/slide[0-9]+\.xml',name)]==['ppt/slides/slide1.xml']
        root=xml('ppt/slides/slide1.xml');tree=root.find('{'+P+'}cSld/{'+P+'}spTree');assert tree is not None
        shapes=tree.findall('{'+P+'}sp');assert len(shapes)==1
        shape=shapes[0];text_box=shape.find('{'+P+'}nvSpPr/{'+P+'}cNvSpPr')
        assert text_box is not None and text_box.get('txBox')=='1' and shape.find('.//{'+P+'}ph') is None
        assert not any(list(shape.iter('{'+A+'}'+name)) for name in ('fld','buChar','buAutoNum','buBlip','br'))
        paragraphs=shape.findall('{'+P+'}txBody/{'+A+'}p');assert len(paragraphs)==1
        text=''.join(node.text or '' for node in paragraphs[0].iter('{'+A+'}t'))
        assert not any(ch in text for ch in '\r\n\t')
        return dict(value,text=_text(text),paragraphCount=1,plainParagraph=True,nonPlaceholderTextBox=True)


def _paragraph(context,call):
    before=_text(call(context.getText));count=_integer(call(context.getCharacterCount))
    caret=_integer(call(context.getCaretPosition),-1)
    start=_integer(call(context.getSelectionStart),-1);end=_integer(call(context.getSelectionEnd),-1)
    after=_text(call(context.getText))
    return dict(textBefore=before,textAfter=after,characterCount=count,caretPosition=caret,
                selectionStart=start,selectionEnd=end)


def _path_proxies(root,path,call,*,retained=None):
    """Check identities before querying each child; recheck every ancestor."""
    assert isinstance(path,list) and len(path)<=10
    assert all(type(index) is int and 0<=index<64 for index in path)
    nodes=[root]
    if retained is not None:assert len(retained)==len(path)+1 and root==retained[0]
    for depth,index in enumerate(path):
        parent=nodes[-1];context=call(parent.getAccessibleContext)
        child=call(context.getAccessibleChild,index)
        if retained is not None:
            assert child==retained[depth+1], 'Retained accessible target ancestry changed'
        child_context=call(child.getAccessibleContext)
        assert call(child_context.getAccessibleParent)==parent
        assert call(child_context.getAccessibleIndexInParent)==index
        assert call(context.getAccessibleChild,index)==child
        nodes.append(child)
    return nodes


def require_edit_context(value,module,child_hwnd):
    assert module in PREFIXES and isinstance(value,dict)
    assert value.get('kind')=='actual-gui-editing-context' and value.get('module')==module
    assert value.get('sourceTag')==SOURCE and value.get('readOnly') is True and value.get('targetStable') is True
    assert type(value.get('childHwnd')) is int and value['childHwnd']==child_hwnd
    if module=='writer':
        for key in ('cursorCollapsed','cursorTextIsBody'):assert type(value.get(key)) is bool
        assert type(value.get('bodyEndComparison')) is int and -32768<=value['bodyEndComparison']<=32767
        _text(value.get('textBefore'));_text(value.get('textAfter'))
        binding=value.get('writerBinding');assert isinstance(binding,dict) and binding.get('verified') is True
        for key in ('bodyIdentity','cursorIdentity'):assert _identity(binding.get(key))
    else:
        assert type(value.get('targetFound')) is bool
        count=_integer(value.get('paragraphCount'));assert count<=16
        paragraph=value.get('paragraph')
        if paragraph is not None:
            assert value['targetFound'] is True and count==1 and isinstance(paragraph,dict)
            _text(paragraph.get('textBefore'));_text(paragraph.get('textAfter'))
            _integer(paragraph.get('characterCount'))
            for key in ('caretPosition','selectionStart','selectionEnd'):_integer(paragraph.get(key),-1)
        binding=value.get('accessibleBinding');assert isinstance(binding,dict) and binding.get('verified') is True
        assert _identity(binding.get('rootIdentity'))
        if module=='calc':
            from calc_pending_input import require_pending_receipt
            pending=value.get('pendingInput');require_pending_receipt(pending,child_hwnd)
            assert binding.get('rootIdentity')==pending['root']['identity']
            assert binding.get('documentIdentity')==pending['document']['identity']
            assert value['targetFound'] is (pending['editor'] is not None)
            if pending['editor'] is not None:
                assert binding.get('editorIdentity')==pending['editor']['identity']
                assert count==len(pending['editor']['paragraphs'])
                if count==1:
                    assert type(binding.get('paragraphIndex')) is int and binding['paragraphIndex']==0
                    assert paragraph is not None and paragraph['textBefore']==paragraph['textAfter']==pending['editor']['text']
            else:assert count==0 and paragraph is None
        else:_require_impress_binding(value)
    return value


def _identity(value):return isinstance(value,str) and re.fullmatch('[a-f0-9]{32}',value) is not None


def _accessible_row(value,role,outer=None):
    from calc_pending_input import _inside,_visible
    assert isinstance(value,dict) and type(value.get('role')) is int and value['role']==role
    state=value.get('stateBits');assert type(state) is int and 0<=state<2**63
    rectangle=value.get('rectangle');assert _inside(rectangle,rectangle)
    if outer is not None:assert _inside(rectangle,outer) and _visible(state), 'Accessible target is not visible inside its owned ancestor'
    return rectangle


def _require_impress_binding(value):
    binding=value['accessibleBinding'];visited=binding.get('visitedCount')
    assert type(visited) is int and 1<=visited<=256
    root=binding.get('root');assert isinstance(root,dict) and root.get('role') in CONTAINER_ROLES|{83}
    outer=_accessible_row(root,root['role'])
    candidates=value.get('candidateObservations');assert isinstance(candidates,list) and len(candidates)<=64
    if 'documentIdentity' not in binding:
        assert not value['targetFound'] and value['paragraphCount']==0 and value['paragraph'] is None and not candidates
        return
    assert _identity(binding['documentIdentity'])
    path=binding.get('documentPath');assert isinstance(path,list) and len(path)<=8
    assert all(type(index) is int and 0<=index<64 for index in path)
    document=_accessible_row(binding.get('document'),83,outer)
    indices=[]
    for candidate in candidates:
        assert isinstance(candidate,dict)
        index=candidate.get('shapeIndex');count=candidate.get('paragraphCount')
        assert type(index) is int and 0<=index<64 and index not in indices
        indices.append(index);assert type(count) is int and 0<=count<=16
        shape=_accessible_row(candidate.get('shape'),52,document)
        if 'caretPosition' in candidate:
            assert count==1 and type(candidate.get('paragraphIndex')) is int and candidate['paragraphIndex']==0
            _integer(candidate['caretPosition'],-1);_accessible_row(candidate.get('paragraph'),41,shape)
    if value['targetFound']:
        for key in ('shapeIdentity','paragraphIdentity'):assert _identity(binding.get(key))
        assert type(binding.get('shapeIndex')) is int and binding['shapeIndex'] in indices
        assert type(binding.get('paragraphIndex')) is int and binding['paragraphIndex']==0
        shape=_accessible_row(binding.get('shape'),52,document)
        _accessible_row(binding.get('paragraph'),41,shape)
        candidate=next(row for row in candidates if row['shapeIndex']==binding['shapeIndex'])
        assert candidate['paragraphCount']==value['paragraphCount']==1 and value['paragraph'] is not None
        assert candidate['shape']==binding['shape'] and candidate['paragraph']==binding['paragraph']
        assert _integer(candidate.get('caretPosition'),-1)>=0
    else:assert value['paragraphCount']==0 and value['paragraph'] is None


def edit_context_ready(value,module,expected_text,child_hwnd):
    require_edit_context(value,module,child_hwnd);_text(expected_text)
    if module=='writer':
        return (value['cursorCollapsed'] and value['cursorTextIsBody'] and value['bodyEndComparison']==0
            and value['textBefore']==value['textAfter']==expected_text)
    paragraph=value['paragraph']
    if not value['targetFound'] or value['paragraphCount']!=1 or paragraph is None:return False
    end=_utf16(expected_text)
    return (paragraph['textBefore']==paragraph['textAfter']==expected_text
        and paragraph['characterCount']==paragraph['caretPosition']==paragraph['selectionStart']==paragraph['selectionEnd']==end)


class EditingContextReader:
    """Retain original proxies. Getter failures propagate; no API-error defaults."""
    def __init__(self,module,frame,controller,model,child_hwnd,*,deadline,clock=time.monotonic):
        assert module in PREFIXES and type(child_hwnd) is int and child_hwnd>0
        self.module,self.frame,self.controller,self.model=module,frame,controller,model
        self.child_hwnd,self.deadline,self.clock=child_hwnd,_time(deadline),clock
        self.body=self.cursor=self.peer=self.root=self.document=self.shape=self.paragraph=None
        self.document_path=self.document_nodes=self.document_children=None
        self.calc=None;self.identities={name:uuid.uuid4().hex for name in ('root','document','shape','paragraph','body','cursor')}
        if module=='writer':
            self.body=self.call(model.getText);self.cursor=self.call(controller.getViewCursor)
        elif module=='calc':
            from calc_pending_input import AccessiblePendingReader
            self.calc=AccessiblePendingReader(frame,child_hwnd,deadline=deadline,clock=clock)
        else:
            import uno
            from calc_pending_input import DISCOVERY_CONTAINER_ROLES,STATE_CONSTANTS
            for name,expected in dict(DISCOVERY_CONTAINER_ROLES,DOCUMENT_PRESENTATION=83,SHAPE=52,PARAGRAPH=41).items():
                assert uno.getConstantByName('com.sun.star.accessibility.AccessibleRole.'+name)==expected
            for name,expected in STATE_CONSTANTS.items():
                assert uno.getConstantByName('com.sun.star.accessibility.AccessibleStateType.'+name)==expected
            self.peer=self.call(frame.getContainerWindow)
            assert self.peer is not None and self.call(self.peer.getWindowHandle,(),1)==child_hwnd
            self.root=self.call(self.peer.getProperty,'XAccessible');assert self.root is not None
    def call(self,function,*args):
        assert _time(self.clock())<self.deadline, 'Original editing-context deadline expired'
        value=function(*args)
        assert _time(self.clock())<self.deadline, 'Original editing-context getter exceeded deadline'
        return value
    def _peer(self):
        assert self.call(self.frame.getContainerWindow)==self.peer
        assert self.call(self.peer.getWindowHandle,(),1)==self.child_hwnd
        assert self.call(self.peer.getProperty,'XAccessible')==self.root, 'Original accessible native peer changed'
    def _node_header(self,accessible,parent=None,index=None):
        from calc_pending_input import _visible
        context=self.call(accessible.getAccessibleContext);role=self.call(context.getAccessibleRole)
        assert type(role) is int
        if parent is not None:
            assert self.call(context.getAccessibleParent)==parent and self.call(context.getAccessibleIndexInParent)==index
            assert self.call(self.call(parent.getAccessibleContext).getAccessibleChild,index)==accessible
        state=self.call(context.getAccessibleStateSet);assert type(state) is int
        return context,role,_visible(state),dict(role=role,stateBits=state)
    def _node_geometry(self,header,*,path=()):
        from calc_pending_input import _inside
        context,role,visible,row=header
        components={};rectangle=None;stage='location'
        try:
            point=self.call(context.getLocationOnScreen)
            stage='point-components';components['x']=point.X;components['y']=point.Y
            stage='size';size=self.call(context.getSize)
            stage='size-components';components['width']=size.Width;components['height']=size.Height
            stage='components';parts=[components[name] for name in ('x','y','width','height')]
            assert all(type(part) is int and -(2**31)<=part<2**31 for part in parts)
            x,y,width,height=parts;rectangle=[x,y,x+width,y+height]
            stage='positive-extent';assert _inside(rectangle,rectangle)
        except BaseException as exc:
            # Only values already returned by this failed attempt are projected.
            # No proxy getters, clock samples, or cleanup run for diagnostics.
            def scalar(value):
                if value is None or type(value) is bool:return value
                if type(value) is int and value.bit_length()<=64:return value
                if type(value) is float and math.isfinite(value):return value
                if type(value) is str and len(value)<=128:return value
                return dict(type=type(value).__name__[:80],valueRetained=False)
            try:
                diagnostic=dict(schemaVersion=1,kind='failed-impress-accessible-geometry',
                    module='impress',sourceTag=SOURCE,childHwnd=self.child_hwnd,
                    readerDeadline=self.deadline,role=scalar(role),stateBits=scalar(row['stateBits']),
                    path=list(path),stage=stage,components={key:scalar(value) for key,value in components.items()},
                    rectangle=rectangle,qualification=False)
                assert len(path)<=10 and all(type(index) is int and 0<=index<64 for index in path)
                assert len(json.dumps(diagnostic,allow_nan=False).encode('utf-8'))<=4096
                exc.impress_geometry_diagnostic=diagnostic
            except BaseException:pass  # Optional local metadata never replaces the original exception.
            raise
        return context,role,visible,dict(row,rectangle=rectangle)
    def _node(self,accessible,parent=None,index=None,*,path=()):
        return self._node_geometry(self._node_header(accessible,parent,index),path=path)
    def _impress(self):
        self._peer();documents=[];visited=0
        _,root_role,_,root_row=self._node(self.root)
        assert root_role in CONTAINER_ROLES|{83}
        # These are local copies of values returned by the original traversal.
        # The failing over-bound node has no header: never query it to diagnose.
        ancestors=[];returned=[];returned_headers=0
        attempt=dict(stage='fixed-bound',failedPath=[],failedNode=None)
        def discover(accessible,parent=None,index=None,path=()):
            nonlocal visited,returned_headers
            node=dict(path=list(path),visit=visited+1,headerReturned=False,
                role=None,stateBits=None,visible=None,childCount=None,childCountReturned=False)
            attempt.update(stage='fixed-bound',failedPath=list(path),failedNode=node)
            visited+=1;assert visited<=256 and len(path)<=8, 'Accessible discovery exceeded fixed bound'
            attempt['stage']='node-header'
            header=self._node_header(accessible,parent,index)
            context,role,visible,_=header
            node.update(headerReturned=True,role=role,stateBits=header[3]['stateBits'],visible=visible)
            ancestors.append(node);returned.append(node);returned_headers+=1
            if len(returned)>16:returned.pop(0)
            if role==83:
                if visible:
                    attempt['stage']='document-geometry'
                    _,_,_,row=self._node_geometry(header,path=path)
                    documents.append((accessible,context,path,row))
                ancestors.pop()
                return
            if role not in CONTAINER_ROLES:ancestors.pop();return
            attempt['stage']='child-count-getter'
            count=self.call(context.getAccessibleChildCount)
            node.update(childCount=count,childCountReturned=True);attempt['stage']='child-count-bound'
            assert type(count) is int and 0<=count<=64
            for child in range(count):
                attempt.update(stage='child-getter',failedPath=list(path+(child,)),
                    failedNode=dict(path=list(path+(child,)),visit=visited+1,headerReturned=False,
                        role=None,stateBits=None,visible=None,childCount=None,childCountReturned=False))
                discover(self.call(context.getAccessibleChild,child),accessible,child,path+(child,))
            ancestors.pop()
        if self.document is None:
            try:discover(self.root)
            except BaseException as exc:
                # Optional projection cannot perform UNO/clock queries, retry,
                # extend a bound, or replace the original exception/deadline.
                try:
                    def scalar(value):
                        if value is None or type(value) is bool:return value
                        if type(value) is int and value.bit_length()<=64:return value
                        return dict(type=type(value).__name__[:80],valueRetained=False)
                    def row(value):
                        return {key:list(item) if key=='path' else scalar(item) for key,item in value.items()}
                    caps=[]
                    if attempt['stage']=='fixed-bound':
                        if visited>256:caps.append('visits')
                        if len(attempt['failedPath'])>8:caps.append('depth')
                    elif attempt['stage']=='child-count-bound':
                        caps.append('children' if type(attempt['failedNode']['childCount']) is int else 'children-type')
                    diagnostic=dict(schemaVersion=1,kind='failed-impress-accessible-discovery',
                        module='impress',sourceTag=SOURCE,childHwnd=self.child_hwnd,
                        readerDeadline=self.deadline,stage=attempt['stage'],failedCaps=caps,
                        limits=dict(visits=256,depth=8,children=64),visitedCount=visited,
                        returnedHeaderCount=returned_headers,failedPath=list(attempt['failedPath']),
                        failedNode=row(attempt['failedNode']),ancestors=[row(value) for value in ancestors],
                        returnedNodes=[row(value) for value in returned],returnedNodeLimit=16,
                        returnedNodesTruncated=returned_headers>len(returned),qualification=False)
                    assert len(json.dumps(diagnostic,allow_nan=False).encode('utf-8'))<=32768
                    exc.impress_discovery_diagnostic=diagnostic
                except BaseException:pass
                raise
            assert len(documents)<=1, 'Original Impress document is ambiguous'
        else:
            _path_proxies(self.root,self.document_path,self.call,retained=self.document_nodes)
            context,role,visible,row=self._node(self.document,path=self.document_path)
            assert role==83 and visible, 'Retained presentation document became unavailable'
            documents=[(self.document,context,tuple(self.document_path),row)]
            visited=len(self.document_path)+1
        result=dict(targetFound=False,paragraphCount=0,paragraph=None,candidateObservations=[],
            accessibleBinding=dict(verified=True,rootIdentity=self.identities['root'],root=root_row,visitedCount=visited))
        if not documents:self._peer();return result
        document,context,path,row=documents[0]
        if self.document is None:self.document=document
        assert document==self.document, 'Retained presentation document changed'
        document_nodes=_path_proxies(self.root,list(path),self.call)
        assert document_nodes[-1]==document
        if self.document_nodes is None:self.document_path,self.document_nodes=list(path),document_nodes
        assert document_nodes==self.document_nodes
        result['accessibleBinding'].update(documentIdentity=self.identities['document'],documentPath=list(path),document=row)
        candidates=[];count=self.call(context.getAccessibleChildCount);assert type(count) is int and 0<=count<=64
        if self.document_children is None:
            self.document_children=[self.call(context.getAccessibleChild,index) for index in range(count)]
        assert count==len(self.document_children), 'Retained presentation child count changed'
        for index in range(count):
            shape=self.call(context.getAccessibleChild,index)
            assert shape==self.document_children[index], 'Retained presentation shape identity changed'
            header=self._node_header(shape,document,index)
            shape_context,role,visible,_=header
            if role!=52 or not visible:continue
            _,_,_,shape_row=self._node_geometry(header,path=path+(index,))
            n=self.call(shape_context.getAccessibleChildCount);assert type(n) is int and 0<=n<=16
            candidate=dict(shapeIndex=index,paragraphCount=n,shape=shape_row)
            result['candidateObservations'].append(candidate)
            if n!=1:continue
            paragraph=self.call(shape_context.getAccessibleChild,0)
            if shape==self.shape:assert paragraph==self.paragraph, 'Retained Outliner paragraph changed'
            header=self._node_header(paragraph,shape,0)
            paragraph_context,role,visible,_=header
            if role!=41 or not visible:continue
            _,_,_,paragraph_row=self._node_geometry(header,path=path+(index,0))
            caret=_integer(self.call(paragraph_context.getCaretPosition),-1)
            candidate.update(paragraphIndex=0,paragraph=paragraph_row,caretPosition=caret)
            if caret>=0:candidates.append((shape,paragraph,paragraph_context,index,shape_row,paragraph_row))
        assert len(candidates)<=1, 'Active Impress text edit is ambiguous'
        if candidates:
            shape,paragraph,paragraph_context,index,shape_row,paragraph_row=candidates[0]
            if self.shape is None:self.shape,self.paragraph=shape,paragraph
            assert shape==self.shape and paragraph==self.paragraph, 'Retained Outliner paragraph changed'
            data=_paragraph(paragraph_context,self.call)
            sc,role,visible,_=self._node(shape,document,index,path=path+(index,))
            assert role==52 and visible and self.call(sc.getAccessibleChildCount)==1, 'Retained Outliner paragraph span changed'
            _,role,visible,_=self._node(paragraph,shape,0,path=path+(index,0))
            assert role==41 and visible, 'Retained active Outliner paragraph became unavailable'
            result.update(targetFound=True,paragraphCount=1,paragraph=data,
                accessibleBinding=dict(verified=True,rootIdentity=self.identities['root'],root=root_row,
                    documentIdentity=self.identities['document'],shapeIdentity=self.identities['shape'],
                    paragraphIdentity=self.identities['paragraph'],documentPath=list(path),shapeIndex=index,
                    paragraphIndex=0,document=row,shape=shape_row,paragraph=paragraph_row,visitedCount=visited))
        elif self.shape is not None:raise AssertionError('Retained active Outliner edit disappeared')
        assert self.call(context.getAccessibleChildCount)==len(self.document_children), 'Retained presentation child count changed'
        for index,child in enumerate(self.document_children):
            assert self.call(context.getAccessibleChild,index)==child, 'Retained presentation shape identity changed'
        _path_proxies(self.root,list(path),self.call,retained=document_nodes)
        self._peer();return result
    def read(self):
        value=dict(kind='actual-gui-editing-context',module=self.module,sourceTag=SOURCE,
            readOnly=True,targetStable=True,childHwnd=self.child_hwnd)
        if self.module=='writer':
            assert self.call(self.model.getText)==self.body and self.call(self.controller.getViewCursor)==self.cursor
            before=_text(self.call(self.body.getString))
            collapsed=self.call(self.cursor.isCollapsed);assert type(collapsed) is bool
            parent=self.call(self.cursor.getText);end=self.call(self.cursor.getEnd);body_end=self.call(self.body.getEnd)
            comparison=self.call(self.body.compareRegionEnds,end,body_end)
            value.update(textBefore=before,textAfter=_text(self.call(self.body.getString)),cursorCollapsed=collapsed,
                cursorTextIsBody=parent==self.body,bodyEndComparison=comparison,
                writerBinding=dict(verified=True,bodyIdentity=self.identities['body'],cursorIdentity=self.identities['cursor']))
            assert self.call(self.model.getText)==self.body and self.call(self.controller.getViewCursor)==self.cursor
        elif self.module=='calc':value.update(self.calc.read_edit_context())
        else:value.update(self._impress())
        return require_edit_context(value,self.module,self.child_hwnd)
    def release(self):
        if self.calc is not None:
            self.calc.semantic_paragraph=None;self.calc.release();self.calc=None
        self.body=self.cursor=self.peer=self.root=self.document=self.shape=self.paragraph=None
        self.document_path=self.document_nodes=self.document_children=None
        self.model=self.controller=self.frame=None


def capture_calc_edit_context(reader):
    """Separate new API: legacy read()/receipt contract remains unchanged."""
    pending=reader.read();value=dict(targetFound=False,paragraphCount=0,paragraph=None,pendingInput=pending,
        accessibleBinding=dict(verified=True,rootIdentity=reader.identities['root'],documentIdentity=reader.identities['document']))
    if pending['editor'] is None:return value
    clock=reader.clock;deadline=reader.deadline
    def call(function,*args):
        assert _time(clock())<deadline, 'Original editing-context deadline expired'
        result=function(*args)
        assert _time(clock())<deadline, 'Original editing-context getter exceeded deadline'
        return result
    document_path=pending['document']['indexPath'];editor_path=pending['editor']['indexPath']
    nodes=_path_proxies(reader.root,editor_path,call)
    assert nodes[len(document_path)]==reader.document and nodes[-1]==reader.editor
    context=call(reader.editor.getAccessibleContext);count=call(context.getAccessibleChildCount)
    assert type(count) is int and 0<=count<=16
    value.update(targetFound=True,paragraphCount=count)
    value['accessibleBinding'].update(editorIdentity=reader.identities['editor'])
    if count!=1:
        _path_proxies(reader.root,editor_path,call,retained=nodes)
        call(reader._verify_peer)
        return value
    paragraph=call(context.getAccessibleChild,0);pc=call(paragraph.getAccessibleContext)
    assert call(pc.getAccessibleRole)==41 and call(pc.getAccessibleParent)==reader.editor and call(pc.getAccessibleIndexInParent)==0
    retained=getattr(reader,'semantic_paragraph',paragraph)
    assert paragraph==retained, 'Retained A1 editing paragraph changed'
    reader.semantic_paragraph=retained
    data=_paragraph(pc,call)
    assert call(context.getAccessibleChildCount)==count, 'Retained A1 paragraph span changed'
    assert call(context.getAccessibleChild,0)==retained and call(pc.getAccessibleParent)==reader.editor
    _path_proxies(reader.root,editor_path,call,retained=nodes)
    call(reader._verify_peer)
    assert data['textBefore']==data['textAfter']==pending['editor']['text'], 'A1 buffer changed inside its getter bracket'
    value.update(paragraph=data)
    value['accessibleBinding'].update(editorIdentity=reader.identities['editor'],paragraphIndex=0)
    return value


NATIVE_KEYS=frozenset(('shellPid','shellCreationTime','officePid','officeCreationTime',
    'expectedImage','suiteHwnd','parentHwnd','childHwnd','rootHwnd'))
MAX_SAMPLES=120
MAX_CONTEXT_BYTES=8*1024*1024
MAX_INVENTORY_BYTES=4*1024*1024
MAX_ENCODED_INVENTORY_BYTES=6*1024*1024
INVENTORY_ENCODING='zlib-base64-v1'


def _encode_inventory(raw):
    """Retain exact packaged bytes without multiplying pretty JSON escaping."""
    assert isinstance(raw,bytes) and 0<len(raw)<=MAX_INVENTORY_BYTES, 'Original inventory exceeds its finite bound'
    data=base64.b64encode(zlib.compress(raw,6)).decode('ascii')
    assert len(data)<=MAX_ENCODED_INVENTORY_BYTES, 'Encoded inventory exceeds its finite bound'
    return dict(encoding=INVENTORY_ENCODING,rawBytes=len(raw),data=data)


def _inventory(context):
    """Decode only the source-fixed codec, then verify the original byte pin."""
    assert 'inventoryJson' not in context, 'Legacy raw inventory is not current semantic evidence'
    evidence=context.get('inventoryEvidence')
    assert isinstance(evidence,dict) and set(evidence)=={'encoding','rawBytes','data'}, 'Incomplete encoded inventory evidence'
    assert evidence['encoding']==INVENTORY_ENCODING, 'Unexpected inventory encoding'
    size=evidence['rawBytes'];data=evidence['data']
    assert type(size) is int and 0<size<=MAX_INVENTORY_BYTES, 'Original inventory exceeds its finite bound'
    assert isinstance(data,str) and 0<len(data)<=MAX_ENCODED_INVENTORY_BYTES, 'Encoded inventory exceeds its finite bound'
    try:
        packed=base64.b64decode(data.encode('ascii'),validate=True)
        assert base64.b64encode(packed).decode('ascii')==data, 'Noncanonical inventory base64'
        decoder=zlib.decompressobj()
        raw=decoder.decompress(packed,MAX_INVENTORY_BYTES+1)
    except (ValueError,zlib.error) as exc:
        raise AssertionError('Malformed encoded inventory') from exc
    assert len(raw)<=MAX_INVENTORY_BYTES, 'Inventory decoded beyond its finite bound'
    assert decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail, 'Incomplete or trailing inventory stream'
    assert len(raw)==size, 'Original inventory byte count changed'
    assert hashlib.sha256(raw).hexdigest()==context['inventorySha256'], 'Original inventory hash changed'
    inventory=json.loads(raw.decode('utf-8'))
    assert isinstance(inventory,dict), 'Original inventory is not a JSON object'
    return inventory


def _phase(module,phase,prefix):
    assert module in PREFIXES and phase in ('pre','post'), 'Unknown IME semantic phase/module'
    assert (prefix is None if phase=='pre' else prefix==PREFIXES[module]), 'Nonexact IME semantic prefix'


def _native(value,suite):
    from writer_model_barrier import _path
    assert isinstance(value,dict) and set(value)==NATIVE_KEYS, 'Incomplete original native admission'
    for key in NATIVE_KEYS-{'expectedImage'}:
        assert type(value[key]) is int and 0<value[key]<2**64, 'Invalid original native admission: '+key
    assert value['suiteHwnd']==value['rootHwnd'] and value['shellPid']!=value['officePid']
    assert _path(value['expectedImage'])==_path(str(suite))/'Office/program/soffice.bin'
    return value


def _same_native(left,right):
    from writer_model_barrier import _path
    for key in NATIVE_KEYS:
        if key=='expectedImage':assert _path(left[key])==_path(right[key]), 'Original engine image changed'
        else:assert type(left[key]) is int and left[key]==right[key], 'Original native admission changed: '+key


def _prefix_evidence(record,module,native,*,setup_deadline,pre_finished,post_started):
    """Actual one-time physical prefix intent; semantic text is checked separately."""
    from ascii_editor_input import US_LAYOUT,require_ascii_receipt
    assert record.get('module')==module and record.get('asciiPrefix')==PREFIXES[module]
    assert type(record.get('prefixInputLayout')) is int and record['prefixInputLayout']==US_LAYOUT
    for key in ('windowHwnd','childHwnd','keyboardFocusHwnd','editorTid'):
        assert type(record.get(key)) is int and record[key]>0, 'Missing actual prefix target: '+key
    assert record['windowHwnd']==native['suiteHwnd'] and record['childHwnd']==native['childHwnd']
    receipts=record.get('asciiEditorInputs')
    assert isinstance(receipts,list) and len(receipts)==1, 'Prefix requires exactly one original physical receipt'
    receipt=require_ascii_receipt(receipts[0],PREFIXES[module],record['windowHwnd'],record['childHwnd'])
    assert receipt['pauseSeconds']==.04, 'IME prefix pacing changed'
    assert _time(receipt.get('absoluteDeadline'))==_time(setup_deadline), 'Prefix used another setup deadline'
    assert (_time(pre_finished)<=_time(receipt.get('startedAt'))<=_time(receipt.get('finishedAt'))
        <=_time(post_started)<setup_deadline), 'Actual prefix does not follow PRE cleanup and precede POST'
    for action in receipt['actions']:
        for side in ('before','after'):
            row=action[side]
            assert type(row['focusHwnd']) is int and row['focusHwnd']==record['keyboardFocusHwnd']
            assert type(row['editorThreadId']) is int and row['editorThreadId']==record['editorTid']
    return receipt


def _source_uri(path):
    """No host-dependent I/O in replay of a Windows or POSIX absolute path."""
    assert isinstance(path,str) and path
    parsed=PureWindowsPath(path) if PureWindowsPath(path).is_absolute() else PurePosixPath(path)
    assert parsed.is_absolute(), 'Semantic source path is not absolute'
    return parsed.as_uri()


def _sample(observation,context,inventory,*,previous=None):
    """Validate all ownership/safety first; only typed GUI states may be pending."""
    from writer_model_barrier import require_original_shell,require_python_identity
    from writer_model_reader import require_owned_model_observation,require_calc_a1_selection
    from calc_pending_input import require_pending_receipt
    from calc_save_smoke import require_uncommitted_cells
    module=context['module'];suite=context['suiteRoot'];native=context['expectedNative']
    binding=observation['bindingBefore'];_same_native(binding,native)
    assert binding['documentUrl']==context['expectedUrl'], 'Semantic reader document URL changed'
    require_owned_model_observation(observation,binding,suite,
        expected_service=SERVICES[module],getter_contract=GETTERS[module])
    require_original_shell(context['originalShell'],binding,suite)
    require_python_identity(observation['pythonIdentity'],suite,inventory,context['inventorySha256'])
    assert context['startedAt']<=_time(observation['readStartedAt'])<=_time(observation['readFinishedAt'])<context['readerDeadline'], 'Semantic read exceeded its original deadline'
    if previous is not None:
        assert previous['bindingBefore']==binding, 'Retained semantic reader binding changed'
        assert _time(previous['readFinishedAt'])<=_time(observation['readStartedAt']), 'Semantic sample order changed'
        for key in ('pid','creationTime','image','handleValue','jobHandleValue'):
            assert observation['readerProcess'][key]==previous['readerProcess'][key], 'Retained semantic helper changed'
        key='writerBinding' if module=='writer' else 'accessibleBinding'
        before,after=previous['editContext'][key],observation['editContext'][key]
        for name in ('bodyIdentity','cursorIdentity','rootIdentity','documentIdentity','editorIdentity',
                     'shapeIdentity','paragraphIdentity','documentPath','shapeIndex','paragraphIndex'):
            if name in before:assert after.get(name)==before[name], 'Retained GUI editing identity changed: '+name
    baseline=context['baseline'];phase=context['phase']
    expected=baseline['text']+(context['expectedPrefix'] if phase=='post' else '')
    modified=observation['isModified'];assert type(modified) is bool
    if phase=='pre':assert modified is False, 'Original IME document is already modified'
    if module=='calc':
        require_uncommitted_cells(observation,baseline['cells'])
        require_calc_a1_selection(observation['calcSelection'])
        require_pending_receipt(observation['editContext']['pendingInput'],native['childHwnd'],
            previous=previous['editContext']['pendingInput'] if previous is not None else None)
    if module=='writer':assert observation.get('bodyText')==observation['editContext']['textAfter'], 'Writer model/body observation disagrees'
    ready=edit_context_ready(observation['editContext'],module,expected,native['childHwnd'])
    if module=='writer' and phase=='post':ready=ready and modified is True
    if module=='calc' and ready:
        require_pending_receipt(observation['editContext']['pendingInput'],native['childHwnd'],expected,require_editor=True)
    return ready


def require_ime_semantic_context(context,*,module,expected_native,setup_deadline,now,
                                 phase='pre',expected_prefix=None):
    """Pure replay of original getter observations and their natural cleanup."""
    from writer_model_reader import require_model_reader_cleanup
    _phase(module,phase,expected_prefix)
    assert isinstance(context,dict) and type(context.get('schemaVersion')) is int and context['schemaVersion']==1
    assert context.get('kind')=='ime-semantic-editing-context' and context.get('success') is True
    assert context.get('module')==module and context.get('phase')==phase and context.get('expectedPrefix')==expected_prefix
    suite=context['suiteRoot'];_native(expected_native,suite);_native(context['expectedNative'],suite)
    _same_native(context['expectedNative'],expected_native)
    start=_time(context['startedAt']);deadline=_time(context['readerDeadline']);setup=_time(setup_deadline)
    finish=_time(context['finishedAt']);current=_time(now)
    assert _time(context['setupDeadline'])==setup and start<deadline==min(setup,start+12.)
    assert 0<setup-start<=60. and start<=finish<=current<setup and finish<deadline, 'IME semantic context deadline/order changed'
    assert context.get('cleanupErrors')==[] and context.get('nativeImeObserved') is False
    raw=context['sourceBytesHex'];assert isinstance(raw,str) and len(raw)<=32*1024*1024
    original=bytes.fromhex(raw);assert original.hex()==raw
    baseline=fixture_baseline(module,original);assert context['baseline']==baseline
    assert context.get('diskBeforeSha256')==context.get('diskAfterSha256')==baseline['sourceSha256']
    assert _source_uri(context['sourcePath'])==context['expectedUrl']
    inventory=_inventory(context)
    observations=context['observations'];assert isinstance(observations,list) and 1<=len(observations)<=MAX_SAMPLES
    timings=context['sampleTimings'];assert isinstance(timings,list) and len(timings)==len(observations)
    previous=None
    for index,observation in enumerate(observations):
        timing=timings[index]
        assert isinstance(timing,dict) and set(timing)=={'requestedAt','receivedAt'}
        assert start<=_time(timing['requestedAt'])<=_time(observation['readStartedAt'])<=_time(observation['readFinishedAt'])<=_time(timing['receivedAt'])<deadline, 'Actual semantic request/receive order changed'
        if index:assert _time(timings[index-1]['receivedAt'])<=_time(timing['requestedAt'])
        ready=_sample(observation,context,inventory,previous=previous)
        assert ready is (index==len(observations)-1), 'Semantic poll history differs from actual first readiness'
        previous=observation
    assert context['observation']==observations[-1]
    cleanup=context['cleanup']
    require_model_reader_cleanup(cleanup,previous['bindingBefore'],deadline,
        expected_service=SERVICES[module],getter_contract=GETTERS[module])
    assert _time(previous['readFinishedAt'])<=_time(cleanup['startedAt'])<=_time(cleanup['finishedAt'])<=finish<deadline, 'Semantic natural cleanup order changed'
    if phase=='post':
        prior=context['preContext']
        require_ime_semantic_context(prior,module=module,expected_native=expected_native,
            setup_deadline=setup,now=start,phase='pre')
        assert prior['sourcePath']==context['sourcePath'] and prior['baseline']==baseline
        assert prior['originalShell']==context['originalShell'] and prior['inventorySha256']==context['inventorySha256']
        assert prior['observation']['bindingBefore']['privatePipe']==previous['bindingBefore']['privatePipe']
        _prefix_evidence(context['asciiEvidence'],module,expected_native,setup_deadline=setup,
            pre_finished=prior['finishedAt'],post_started=start)
    else:assert 'preContext' not in context and 'asciiEvidence' not in context
    assert len(json.dumps(context,ensure_ascii=False).encode('utf-8'))<=MAX_CONTEXT_BYTES, 'IME semantic evidence exceeds its finite bound'
    return context


def observe_ime_semantic_setup(suite,source,original_bytes,record,setup_deadline,*,
        original_shell,expected_native,require_current,phase='pre',expected_prefix=None,
        reader_factory=None,clock=time.monotonic,pause=time.sleep):
    """Observe without input; keep the original setup/reader deadline through close."""
    from writer_model_reader import OwnedModelReader,require_model_reader_cleanup
    from writer_style_smoke import _packaged_identity_file
    suite,source=Path(suite).resolve(),Path(source).absolute()
    module=record.get('module');_phase(module,phase,expected_prefix)
    started=_time(clock());setup_deadline=_time(setup_deadline)
    assert 0<setup_deadline-started<=60., 'Original IME setup budget expired or was extended'
    deadline=min(setup_deadline,started+12.)
    context=dict(schemaVersion=1,kind='ime-semantic-editing-context',module=module,phase=phase,
        success=False,startedAt=started,setupDeadline=setup_deadline,readerDeadline=deadline,
        expectedPrefix=expected_prefix,expectedNative=copy.deepcopy(expected_native),
        suiteRoot=str(suite),sourcePath=str(source),expectedUrl=source.as_uri(),
        originalShell=copy.deepcopy(original_shell),observations=[],sampleTimings=[],cleanupErrors=[],nativeImeObserved=False)
    prior=record.get('imeSemanticContext');history=record.setdefault('imeSemanticContexts',[])
    assert isinstance(history,list), 'Invalid actual semantic phase history'
    record['imeSemanticContext']=context
    reader=None;primary=None;cleanup_failures=[]
    try:
        require_current();_native(expected_native,suite)
        if phase=='pre':
            assert not history and prior is None, 'PRE semantic observation must be fresh'
            assert not record.get('asciiPrefix') and not record.get('asciiEditorInputs'), 'PRE observation follows an existing ASCII prefix'
        else:
            assert len(history)==1 and history[0] is prior, 'POST requires the exact actual PRE context'
            require_ime_semantic_context(prior,module=module,expected_native=expected_native,
                setup_deadline=setup_deadline,now=started,phase='pre')
            context['preContext']=copy.deepcopy(prior)
            keys=('module','asciiPrefix','prefixInputLayout','windowHwnd','childHwnd','keyboardFocusHwnd','editorTid','asciiEditorInputs')
            context['asciiEvidence']={key:copy.deepcopy(record[key]) for key in keys}
            _prefix_evidence(context['asciiEvidence'],module,expected_native,setup_deadline=setup_deadline,
                pre_finished=prior['finishedAt'],post_started=started)
        history.append(context)
        baseline=fixture_baseline(module,original_bytes)
        context.update(baseline=baseline,sourceBytesHex=original_bytes.hex())
        if phase=='post':assert prior['sourcePath']==str(source) and prior['baseline']==baseline and prior['originalShell']==original_shell
        assert source.is_file() and not source.is_symlink(), 'Original owned IME file is missing or linked'
        context['diskBeforeSha256']=hashlib.sha256(source.read_bytes()).hexdigest()
        assert context['diskBeforeSha256']==baseline['sourceSha256'], 'Original IME disk file changed before semantic capture'
        identity,raw=_packaged_identity_file(suite,'suite-inventory.json')
        context.update(inventoryEvidence=_encode_inventory(raw),inventorySha256=identity['sha256'])
        inventory=_inventory(context)
        require_current();assert _time(clock())<deadline, 'Semantic reader construction exceeded original deadline'
        factory=OwnedModelReader if reader_factory is None else reader_factory
        reader=factory(suite,source.parent/('ime-semantic-reader-'+phase),
            expected_service=SERVICES[module],getter_contract=GETTERS[module],
            shell_pid=expected_native['shellPid'],expected_shell_creation=expected_native['shellCreationTime'],
            suite_hwnd=expected_native['suiteHwnd'],parent_hwnd=expected_native['parentHwnd'],
            child_hwnd=expected_native['childHwnd'],office_pid=expected_native['officePid'],
            expected_url=source.as_uri(),clock=clock)
        context['readerStartAttempted']=True
        previous=None
        for index in range(MAX_SAMPLES):
            require_current();assert _time(clock())<deadline, 'Original semantic polling deadline expired'
            requested=_time(clock())
            observation=reader.start(deadline) if index==0 else reader.read(deadline)
            received=_time(clock())
            context['observations'].append(observation);context['observation']=observation
            context['sampleTimings'].append(dict(requestedAt=requested,receivedAt=received))
            assert requested<=_time(observation['readStartedAt'])<=_time(observation['readFinishedAt'])<=received<deadline, 'Actual semantic request/receive order changed'
            require_current()
            ready=_sample(observation,context,inventory,previous=previous)
            assert _time(clock())<deadline, 'Semantic observation arrived after its original deadline'
            assert len(json.dumps(context,ensure_ascii=False).encode('utf-8'))<=MAX_CONTEXT_BYTES
            if ready:break
            previous=observation
            assert index+1<MAX_SAMPLES, 'Semantic editing context never reached supported readiness'
            remaining=deadline-_time(clock());assert remaining>0, 'Original semantic polling deadline expired'
            pause(min(.05,remaining))
        assert ready, 'Semantic editing context never became ready'
    except BaseException as exc:
        primary=exc;context['error']=type(exc).__name__[:80]+': '+str(exc)[:1024]
        raise
    finally:
        if reader is not None:
            try:
                context['cleanup']=reader.close(deadline)
                if context['observations']:
                    require_model_reader_cleanup(context['cleanup'],context['observations'][-1]['bindingBefore'],deadline,
                        expected_service=SERVICES[module],getter_contract=GETTERS[module])
                    assert _time(context['observations'][-1]['readFinishedAt'])<=_time(context['cleanup']['startedAt']), 'Semantic reader cleanup precedes observation'
            except BaseException as exc:
                cleanup_failures.append(exc);context['cleanupErrors'].append(type(exc).__name__[:80]+': '+str(exc)[:1024])
        if primary is None and not cleanup_failures:
            try:
                assert source.is_file() and not source.is_symlink()
                context['diskAfterSha256']=hashlib.sha256(source.read_bytes()).hexdigest()
                require_current();context['finishedAt']=_time(clock());context['success']=True
                require_ime_semantic_context(context,module=module,expected_native=expected_native,
                    setup_deadline=setup_deadline,now=context['finishedAt'],phase=phase,expected_prefix=expected_prefix)
                require_current()
                finished=_time(clock())
                assert context['finishedAt']<=finished<deadline, 'Semantic replay/return exceeded its original reader deadline'
                context['finishedAt']=finished
            except BaseException as exc:
                context['success']=False;cleanup_failures.append(exc)
                context['cleanupErrors'].append(type(exc).__name__[:80]+': '+str(exc)[:1024])
        if primary is None and cleanup_failures:
            context['error']=type(cleanup_failures[0]).__name__[:80]+': '+str(cleanup_failures[0])[:1024]
            raise cleanup_failures[0]
    return context
