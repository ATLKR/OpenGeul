"""A pointer-only Save item in the original, already-open WinForms File menu.

No native keyboard-menu focus rule is changed. A missing UIA/native ownership
bridge is an error before input, including when a visible menu looks plausible.
"""
from __future__ import annotations
import copy
import math
import json
from pathlib import Path
from types import SimpleNamespace
import time

from owned_control_actions import NativeControlProbe, _inside, _integer, _window
from owned_control_actions import CAP
from suite_window_activation import Point

BASE_CAPTION = 'OpenGeul Base — 다른 이름으로 저장'


def _time(value):
    assert type(value) in (int,float) and math.isfinite(value) and value >= 0
    return value


def _runtime(value):
    assert isinstance(value,list) and 0<len(value)<=64
    assert all(type(part) is int and -(2**31)<=part<2**31 for part in value), 'Invalid native UIA runtime identity'


def _point(value):
    assert isinstance(value,list) and len(value)==2
    assert all(type(part) is int and -(2**31)<=part<2**31 for part in value), 'Invalid physical Save point'


def detached_save_menu_action(action):
    assert isinstance(action,dict)
    raw=json.dumps(action,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    assert len(raw)<=CAP, 'Embedded Save action exceeds existing control receipt bound'
    return json.loads(raw)


def file_click_anchor(record, document, original, started):
    matches = [(index, row) for index, row in enumerate(record['ownedControlActions'][:-1])
               if row.get('purpose') == 'FILE_MENU' and row.get('documentHwnd') == document]
    assert len(matches) == 1, 'Save requires one original File pointer action'
    (index, row), = matches
    assert row['success'] is True and row['shortcut'] is None
    assert (row['clickAttempts'], row['inputCallAttempts'], row['requestedInputs'], row['insertedInputs']) == (1, 1, 2, 2)
    assert row['nativeInsertionCountVerified'] is True and row['originalProcess'] == original
    for key in ('clickAttempts','inputCallAttempts','requestedInputs','insertedInputs'):_integer(row[key])
    for key in ('startedAt','finishedAt','deadline'):_time(row[key])
    assert row['startedAt'] <= row['finishedAt'] <= started and row['finishedAt'] <= row['deadline']
    before = row['before']; file = before['control']; ancestry = before['ancestry']
    assert file['pid'] == original['pid'] and file['name'] == '파일' and file['controlType'] == 'MenuItem'
    assert ancestry[0]['runtimeId'] == file['runtimeId'] and ancestry[-1]['nativeHwnd'] == document
    return dict(index=index, control=copy.deepcopy(file), ancestry=copy.deepcopy(ancestry),
                document=copy.deepcopy(before['document']))


def home_engine_witness(record, document, attachment):
    rows = [row for row in record.get('attachments', []) if row['hwnd'] == document]
    if not rows:
        assert record.get('kind') != 'tile', 'Home Save lacks its original retained engine witness'
        return None, 'first-native-measurement'
    assert len(rows) == 1, 'Home Save attachment is ambiguous'
    row = rows[0]
    assert all(key in row for key in ('liveProcessBinding', 'officeCreationTime', 'officeImage')), 'Home Save lacks its original retained engine witness'
    live = row['liveProcessBinding']; creation = row['officeCreationTime']; image = row['officeImage']
    _integer(creation)
    for value in (row['officePid'],live['pid'],live['creationTime'],live['nativeCreation']['fileTime'],live['waitResult']):_integer(value)
    assert live['pid'] == attachment['officePid'] == row['officePid'] and live['waitResult'] == 258
    assert live['creationTime'] == live['nativeCreation']['fileTime'] == creation
    assert live['nativeImage'].casefold() == live['expectedImage'].casefold() == image.casefold()
    _integer(live['handleValue'])
    return dict(pid=row['officePid'], image=image, creationTime=creation), 'existing-home-retained-engine'


def require_save_menu_target(value, document, pid, caption, file_anchor):
    assert caption == BASE_CAPTION, 'Save-menu pointer is limited to new Base'
    doc, scope, control, gui = (value[k] for k in ('document', 'scope', 'control', 'gui'))
    for row in (doc,scope):
        for key in ('hwnd','pid','threadId','rootHwnd'):_integer(row[key])
    _integer(scope['ownerHwnd'])
    for key in ('hwnd','pid','threadId','rootHwnd'):_integer(file_anchor['document'][key])
    _window(doc, document, pid); _window(scope, scope['hwnd'], pid)
    assert all(doc[k] == file_anchor['document'][k] for k in ('hwnd', 'pid', 'threadId', 'rootHwnd')), 'Save original document changed'
    assert scope['hwnd'] != document and scope['ownerHwnd'] == document and scope['threadId'] == doc['threadId'], 'Save popup is not owned by the original document thread'
    assert control['name'] == '저장' and control['controlType'] == 'MenuItem' and control['pid'] == pid
    assert control['visible'] is control['enabled'] is True and control['runtimeId']
    _runtime(control['runtimeId']);_integer(control['nativeHwnd'],positive=False);_integer(control['pid'])
    assert _inside(control['rectangle'], scope['rectangle']), 'Save rectangle escaped its original popup'
    chain = value['ancestry']; bridge = value['saveMenuBridge']
    assert 5 <= len(chain) <= 32 and all(row['pid'] == pid and row['runtimeId'] for row in chain)
    for row in chain:
        _runtime(row['runtimeId']);_integer(row['pid']);_integer(row['nativeHwnd'],positive=False)
    assert all(chain[0][key]==control[key]for key in ('runtimeId','pid','nativeHwnd','controlType')) and chain[-1]['nativeHwnd'] == document, 'Save control differs from its raw ancestry'
    menu, file, bar = (bridge[k] for k in ('menuIndex', 'fileIndex', 'menuBarIndex'))
    assert all(type(index) is int for index in (menu, file, bar)) and 0 < menu < file < bar < len(chain)-1, 'Unknown Save/dropdown/File/MenuBar ownership bridge'
    assert (chain[menu]['controlType'], chain[file]['controlType'], chain[bar]['controlType'], chain[-1]['controlType']) == ('Menu', 'MenuItem', 'MenuBar', 'Window')
    assert bridge['fileElementEquals'] is bridge['documentElementEquals'] is True
    frozen = file_anchor['control']; current = bridge['fileControl']
    _integer(file_anchor['index'],positive=False)
    for row in (frozen,current):_runtime(row['runtimeId']);_integer(row['nativeHwnd'],positive=False);_integer(row['pid'])
    assert all(current[k] == frozen[k] for k in ('runtimeId', 'pid', 'nativeHwnd', 'controlType', 'name')), 'Original File UIA identity was replaced'
    assert chain[file]['runtimeId'] == frozen['runtimeId'] and bridge['fileAncestry'] == file_anchor['ancestry']==chain[file:], 'Original File ancestry changed'
    for row in file_anchor['ancestry']:
        _runtime(row['runtimeId']);_integer(row['pid']);_integer(row['nativeHwnd'],positive=False)
    assert bridge['nativeOwnerChain'] == [scope['hwnd'], document], 'Unknown native Save-popup owner bridge'
    for hwnd in bridge['nativeOwnerChain']:_integer(hwnd)
    foreground = value['foreground']
    for key in ('hwnd','pid','threadId','rootHwnd'):_integer(foreground[key])
    assert foreground['hwnd'] == foreground['rootHwnd'] and foreground['pid'] == pid and foreground['threadId'] == doc['threadId']
    assert foreground['hwnd'] in (document, scope['hwnd']), 'Foreign foreground before Save-menu pointer'
    assert gui['threadId'] == doc['threadId'] and gui['activeHwnd'] == document
    for key in ('threadId','activeHwnd','focusHwnd','focusPid','focusRootHwnd','captureHwnd','menuOwnerHwnd'):_integer(gui[key],positive=False)
    assert gui['focusHwnd'] > 0 and gui['focusPid'] == pid and gui['focusRootHwnd'] in (document, scope['hwnd'])
    assert gui['captureHwnd'] in (0, scope['hwnd']) and gui['menuOwnerHwnd'] in (0, document, scope['hwnd'])
    return dict(document={k:doc[k] for k in ('hwnd', 'pid', 'threadId', 'rootHwnd', 'rectangle')},
                scope={k:scope[k] for k in ('hwnd', 'pid', 'threadId', 'rootHwnd', 'ownerHwnd', 'rectangle')},
                control=control, ancestry=chain, saveMenuBridge=bridge)


def require_save_menu_action(action, shell_pid, document, caption, readiness):
    """Replay the new pointer trigger; never infer a keyboard shortcut."""
    detached_save_menu_action(action)
    assert readiness['saveMenuAction']==action, 'Embedded Save action differs from original raw action'
    assert type(action['schemaVersion']) is int and action['schemaVersion']==1
    assert action['kind'] == 'owned-shell-control-action' and action['purpose'] == 'SAVE_MENU'
    _integer(action['documentHwnd']);_integer(action['dialogHwnd'],positive=False);_integer(action['engineHandle'])
    assert action['success'] is True and action['shortcut'] is None and action['dialogHwnd'] == 0
    assert (action['documentHwnd'], action['caption']) == (document, caption) and caption == BASE_CAPTION
    assert (action['clickAttempts'], action['inputCallAttempts'], action['requestedInputs'], action['insertedInputs']) == (1, 1, 2, 2)
    for key in ('clickAttempts','inputCallAttempts','requestedInputs','insertedInputs','pointerMoveAttempts'):_integer(action[key])
    assert action['pointerMoveAttempts']==1
    assert action['nativeInsertionCountVerified'] is True and action['atomicRecipientDeliveryProved'] is False
    assert action['startedAt'] <= action['engineAdmittedAt'] <= action['finishedAt'] < action['deadline']
    for key in ('startedAt','engineAdmittedAt','finishedAt','deadline'):_time(action[key])
    assert 0 < action['deadline'] - action['startedAt'] <= 5
    assert action['engineHandleClosed'] is True and action['dpiScope']['verified'] is action['dpiScope']['restored'] is True
    original = action['originalProcess']; engine = action['originalEngine']; attachment = action['originalAttachment']
    for key in ('document','parent','child','officePid'):_integer(attachment[key])
    assert attachment['document']==document
    for row in (original,engine):
        for key in ('pid','handleValue','creationTime','waitResult'):_integer(row[key])
    assert original['pid'] == shell_pid and original['waitResult'] == engine['waitResult'] == 258
    assert engine['pid'] == attachment['officePid'] and engine['handleValue'] == action['engineHandle']
    assert type(engine['creationTime']) is int and engine['creationTime'] >= original['creationTime']
    assert action['engineAdmissionBasis'] in ('existing-home-retained-engine', 'first-native-measurement')
    witness = action['originalEngineWitness']
    if action['engineAdmissionBasis'] == 'existing-home-retained-engine':
        assert witness is not None, 'Home Save lacks its original engine witness'
    if witness is not None:
        _integer(witness['pid']);_integer(witness['creationTime'])
        assert all(witness[k] == engine[k] for k in ('pid', 'image', 'creationTime')), 'Earlier Save engine witness changed'
    anchors=[require_save_menu_target(action[key],document,shell_pid,caption,action['saveMenuFileAnchor'])
             for key in ('before','afterMoveIntent','beforeClick','afterClickIntent')]
    assert all(anchor==anchors[0] for anchor in anchors), 'Save recipient changed across durable intent'
    point=action['chosenPhysicalPoint'];rectangle=action['before']['control']['rectangle']
    _point(point);_point(action['pointerReadback']);_point(action['beforeClickCursorReadback'])
    assert point==[(rectangle[0]+rectangle[2])//2,(rectangle[1]+rectangle[3])//2]
    assert action['pointerReadback']==action['beforeClickCursorReadback']==point and action['pointerSetReturned'] is True
    for key in ('beforeMoveHit','afterMoveIntentHit','beforeClickHit','afterClickIntentHit'):
        hit=action[key]
        _point(hit['point'])
        for field in ('hitHwnd','pid','rootHwnd'):_integer(hit[field])
        assert hit['point']==point and hit['pid']==shell_pid and hit['rootHwnd']==anchors[0]['scope']['hwnd']
        assert hit['withinControl'] is hit['uiaMatches'] is True, 'Save physical/UIA hit did not retain original recipient'
    after = action['after']; picker = after['foreground']; uia = after['newPicker']
    for key in ('hwnd','rootHwnd','pid','threadId','ownerHwnd'):_integer(picker[key])
    for key in ('nativeHwnd','pid'):_integer(uia[key])
    _runtime(uia['runtimeId']);_runtime(readiness['uiaRootRuntimeId'])
    for key in ('shellPid','documentHwnd','dialogHwnd'):_integer(readiness[key])
    assert after['accepted'] is True and after['transition'] == 'exact-owned-save-picker'
    assert picker['hwnd'] == picker['rootHwnd'] == readiness['dialogHwnd'] and picker['pid'] == shell_pid
    assert picker['ownerHwnd'] == document and picker['className'] == '#32770' and picker['title'] == caption
    assert picker['threadId']==action['before']['document']['threadId'] and picker['visible'] is picker['enabled'] is True
    assert uia['runtimeId'] == readiness['uiaRootRuntimeId'] and uia['nativeHwnd'] == picker['hwnd'] and uia['pid'] == shell_pid
    assert uia['name']==caption and uia['controlType']=='Window' and uia['visible'] is uia['enabled'] is True
    assert readiness['ready'] is True and readiness['shellPid'] == shell_pid and readiness['documentHwnd'] == document and readiness['caption'] == caption
    assert readiness['trigger']=='owned-save-menu-pointer' and readiness['fileMenuClicks']==readiness['saveMenuClicks']==1 and readiness['saveShortcuts']==0
    for key in ('fileMenuClicks','saveMenuClicks','saveShortcuts'):_integer(readiness[key],positive=False)
    assert action['finishedAt'] <= readiness['startedAt'] <= readiness['finishedAt']
    return action


class NativeSaveMenuProbe(NativeControlProbe):
    def discover_save_menu(self, api, document, original_file, record, receipt):
        self.receipt = receipt
        self.file_anchor = receipt['saveMenuFileAnchor']
        self.file_element = self._call(lambda: original_file.element_info._element)
        self.root_element = self._call(lambda: self.desktop.window(handle=document).wrapper_object().element_info._element)
        raw = self._raw(self.file_element)
        assert all(raw[k] == self.file_anchor['control'][k] for k in ('runtimeId', 'pid', 'nativeHwnd', 'controlType', 'name')), 'Original File control changed before Save discovery'
        found = self._call(self.file_element.FindAll, self.uia.tree_scope['descendants'], self.uia.true_condition)
        count = int(self._call(lambda: found.Length)); assert 0 <= count <= 64, 'Save dropdown exceeds bounded discovery'
        discovery = dict(queryApi='IUIAutomationElement.FindAll', treeScope=4, rawCount=count, candidates=[])
        receipt['saveMenuDiscovery'] = discovery; matches = []
        for index in range(count):
            element = self._call(found.GetElement, index); row = self._raw(element)
            if row['name'] == '저장' and row['controlType'] == 'MenuItem':
                discovery['candidates'].append(row); matches.append(element)
        assert len(matches) == 1, 'The exact original File dropdown must have one Save item'
        self.save_element = matches[0]
        return SimpleNamespace(element_info=SimpleNamespace(_element=self.save_element))

    def target_snapshot(self, api, document, control, dialog, purpose):
        assert purpose == 'SAVE_MENU' and not dialog
        element = self._call(lambda: control.element_info._element)
        assert self._call(self.uia.iuia.CompareElements, element, self.save_element), 'Original Save element was replaced'
        props = self._raw(element); ancestry = []; cursor = element
        partial = dict(control=props, ancestry=ancestry)
        self.receipt['saveMenuLastBridgeRead'] = partial
        file_index = menu_index = bar_index = None; file_equals = root_equals = False
        for _ in range(32):
            row = self._raw(cursor)
            if row['controlType'] == '50009': row['controlType'] = 'Menu'
            ancestry.append({k:row[k] for k in ('runtimeId', 'pid', 'nativeHwnd', 'controlType')})
            index = len(ancestry)-1
            if row['controlType'] == 'Menu' and menu_index is None: menu_index = index
            if self._call(self.uia.iuia.CompareElements, cursor, self.file_element): file_index = index; file_equals = True
            if row['controlType'] == 'MenuBar' and file_index is not None and bar_index is None: bar_index = index
            if self._call(self.uia.iuia.CompareElements, cursor, self.root_element): root_equals = True; break
            cursor = self._call(self.uia.iuia.ControlViewWalker.GetParentElement, cursor)
            assert cursor, 'Save UIA ancestry ended outside original File/document'
        else: raise AssertionError('Save UIA ancestry exceeds bound')
        file_props = self._raw(self.file_element)
        file_ancestry = ancestry[file_index:] if file_index is not None else []
        # This is a read-only hit, before any pointer move. It joins the real
        # separate popup HWND to the UIA item instead of inventing a dialog.
        rectangle = props['rectangle']; point = [(rectangle[0]+rectangle[2])//2, (rectangle[1]+rectangle[3])//2]
        hit = self.point_snapshot(document, point, control)
        partial['physicalHit'] = hit
        assert hit['uiaMatches'] is True and hit['withinControl'] is True, 'Save item is obstructed before admission'
        scope = self._window(hit['rootHwnd']); doc = self._window(document)
        partial.update(scope=scope, document=doc)
        native_chain = self._owner_chain(scope['hwnd'], document)
        # Each owner relation must name the same retained native document
        # thread. The pure policy rejects indirect/unknown popup ownership.
        owners = [self._window(hwnd) for hwnd in native_chain]
        partial.update(nativeOwnerChain=native_chain, nativeOwners=owners)
        assert all(row['pid'] == doc['pid'] and row['threadId'] == doc['threadId'] for row in owners), 'Save popup owner belongs to another process/thread'
        foreground = self._window(self.foreground()); gui = self.native_focus(doc['threadId'])
        bridge = dict(fileElementEquals=file_equals, documentElementEquals=root_equals,
            menuIndex=menu_index, fileIndex=file_index, menuBarIndex=bar_index,
            fileControl=file_props, fileAncestry=file_ancestry, nativeOwnerChain=native_chain)
        return dict(document=doc, scope=scope, control=props, ancestry=ancestry, gui=gui,
                    foreground=foreground, foregroundOwnerChain=self._owner_chain(foreground['hwnd'], document),
                    saveMenuBridge=bridge)

    def transition_snapshot(self, api, process, document, dialog, caption, purpose, control,
                            *, context=None, evidence=None):
        assert purpose == 'SAVE_MENU' and not dialog and caption == BASE_CAPTION
        result = evidence if evidence is not None else {}
        result.update(accepted=False, observationCount=0)
        def budget():
            assert self.clock() < self.deadline, 'Owned Save-menu transition deadline expired'
        while True:
            budget(); assert result['observationCount'] < 501, 'Save-menu transition observation bound exceeded'
            original = self.process_snapshot(process); result['lastOriginalProcess'] = original
            assert original == context['originalProcess'], 'Original Save-menu process generation changed'
            doc = self._window(document); result['lastOriginalDocument'] = doc
            assert all(doc[k] == context['document'][k] for k in ('hwnd', 'pid', 'threadId', 'rootHwnd')), 'Original Save-menu document changed'
            assert doc['visible'] is True and doc['iconic'] is False and doc['cloaked'] == 0
            foreground = self._window(self.foreground()); result['foreground'] = foreground
            result['observationCount'] += 1
            assert foreground['pid'] == process.pid and foreground['threadId'] == doc['threadId'], 'Foreign foreground after Save-menu click'
            if foreground['hwnd'] not in (document, context['scope']['hwnd']):
                assert foreground['rootHwnd'] == foreground['hwnd'] and foreground['ownerHwnd'] == document
                assert foreground['className'] == '#32770' and foreground['title'] == caption, 'Unexpected Save-menu picker'
                assert foreground['visible'] is foreground['enabled'] is True
                element = self._call(lambda: self.desktop.window(handle=foreground['hwnd']).wrapper_object().element_info._element)
                info = self._raw(element); result['newPicker'] = info
                assert info['nativeHwnd'] == foreground['hwnd'] and info['pid'] == process.pid and info['runtimeId']
                assert info['controlType'] == 'Window' and info['name'] == caption and info['visible'] is info['enabled'] is True
                budget(); result.update(accepted=True, transition='exact-owned-save-picker'); return result
            if foreground['hwnd'] != document:
                assert all(foreground[k] == context['scope'][k] for k in ('hwnd', 'pid', 'threadId', 'rootHwnd', 'ownerHwnd')), 'Original Save popup changed after click'
            remaining = self.deadline - self.clock(); assert remaining > 0, 'Owned Save-menu transition deadline expired'
            self._call(time.sleep, min(.01, remaining))
