"""Read actual VCL accessibility objects through the owned engine's private pipe.

This E2E-only reader covers LibreOffice's notebookbar sibling omission in its
Windows MSAA bridge. It does not certify OS screen-reader exposure. No product
worker command or second document is created, and no document state is changed.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROLE_NAMESPACE = 'com.sun.star.accessibility.AccessibleRole'
PAGE_TAB, PAGE_TAB_LIST = 38, 39  # Pinned 26.8.1.1 AccessibleRole.idl.
VISIBLE, SHOWING = 536870912, 16777216
MODULE_SERVICES = {'writer': 'com.sun.star.text.TextDocument',
                   'calc': 'com.sun.star.sheet.SpreadsheetDocument',
                   'impress': 'com.sun.star.presentation.PresentationDocument',
                   'draw': 'com.sun.star.drawing.DrawingDocument'}
_CHILD_FAILURE_KEYS = {'schemaVersion', 'officePid', 'officeCreationTime', 'childHwnd',
                       'moduleCode', 'ownershipStage', 'failure', 'ownedFrames'}


def _validate_child_failure(value, request):
    """Validate only closed numbers; request paths and transport are never read."""
    from numeric_notice import MODULES, SOURCE_FILES, validate_failure_code, validate_failure_frames
    if type(value) is not dict or value.keys() != _CHILD_FAILURE_KEYS:
        raise ValueError('Closed native child failure required')
    for key, expected, maximum in (
            ('schemaVersion', 1, 1), ('officePid', request['officePid'], 0xffffffff),
            ('officeCreationTime', request['creationTime'], 2**64-1),
            ('childHwnd', request['childHwnd'], 2**64-1),
            ('moduleCode', MODULES[request['module']], 4)):
        if (type(expected) is not int or type(value[key]) is not int
                or not 1 <= value[key] <= maximum or value[key] != expected):
            raise ValueError('Native child failure identity differs')
    if type(value['ownershipStage']) is not int or value['ownershipStage'] not in (0, 1, 2):
        raise ValueError('Unknown native child ownership stage')
    failure = validate_failure_code(value['failure'])
    frames = validate_failure_frames(value['ownedFrames'])
    if (not frames or not failure['fileCode'] or frames[-1] != [failure['fileCode'], failure['line']]
            or not any(row[0] == SOURCE_FILES['native_accessibility.py'] for row in frames)):
        raise ValueError('Actual native child owned traceback required')
    return dict(value, failure=failure, ownedFrames=frames)


def _decode_child_failure(value, request):
    try:
        if type(value) is not str or not 0 < len(value.encode('utf-8')) <= 1024:
            return None
        def unique(pairs):
            result = {}
            for key, item in pairs:
                if key in result: raise ValueError('Duplicate native child key')
                result[key] = item
            return result
        return _validate_child_failure(json.loads(value, object_pairs_hook=unique), request)
    except Exception:
        return None  # Optional evidence never replaces the original failure.


def attach_child_failure(record, exc):
    """After the normal capture hook, use actual child frames in its one notice."""
    try:
        from numeric_notice import notices_enabled, validate_failure_code, validate_failure_frames
        if (not notices_enabled() or type(record) is not dict or type(exc) is not AssertionError
                or record.get('success') is not False
                or record.get('stage') != 'capture-native-accessible-objects'
                or record.get('case') != 'korean-ui-' + record['module']):
            return False
        child = _validate_child_failure(vars(exc).get('_opengeul_native_accessibility_failure'),
            dict(officePid=record['officePid'], creationTime=record['officeCreationTime'],
                 childHwnd=record['childHwnd'], module=record['module']))
        controller = validate_failure_code(record.get('numericFailure'))
        controller_frames = validate_failure_frames(record.get('numericFailureFrames'))
        record.update(nativeAccessibilityControllerFailure=controller,
                      nativeAccessibilityControllerFrames=controller_frames,
                      nativeAccessibilityChildFailure=child,
                      numericFailure=child['failure'], numericFailureFrames=child['ownedFrames'])
        return True
    except Exception:
        return False


def normalize_label(value):
    return re.sub(r'\s*\([~&_]?[A-Za-z]\)\s*$', '', value).translate(
        str.maketrans('', '', '~&_')).strip()


def private_pipe(arguments):
    accepts = [argument for argument in arguments if argument.startswith('--accept=')]
    assert len(accepts) == 1, 'Expected one private Office transport'
    match = re.fullmatch(r'--accept=pipe,name=(OpenGeul_[0-9a-f]{32});urp;StarOffice.ServiceManager', accepts[0])
    assert match and '--invisible' in arguments and '--headless' not in arguments, 'Owned GUI private-pipe transport is invalid'
    return match.group(1)


def inside(rectangle, outer):
    return (isinstance(rectangle, list) and len(rectangle) == 4
            and all(type(value) is int for value in rectangle)
            and rectangle[0] < rectangle[2] and rectangle[1] < rectangle[3]
            and outer[0] <= rectangle[0] < rectangle[2] <= outer[2]
            and outer[1] <= rectangle[1] < rectangle[3] <= outer[3])


def require_native_tabs(snapshot, office_pid, child, module):
    assert snapshot.get('kind') == 'owned-native-vcl-accessibility', 'Actual native VCL accessibility evidence is required'
    assert snapshot.get('roleNamespace') == ROLE_NAMESPACE and snapshot.get('roleConstants') == {'PAGE_TAB': PAGE_TAB, 'PAGE_TAB_LIST': PAGE_TAB_LIST}, 'Native UNO role namespace differs from the pinned API'
    assert snapshot.get('officePid') == office_pid and snapshot.get('childHwnd') == child, 'Native accessibility engine ownership differs'
    assert snapshot.get('module') == module and snapshot.get('loadedModuleService') == MODULE_SERVICES[module], 'Native accessible frame belongs to another module'
    witness = snapshot.get('witness', {})
    assert witness.get('retainedProcessHandle') and witness.get('imageVerified') and witness.get('creationTimeVerified'), 'Native engine process identity was not retained and verified'
    assert witness.get('hwndVerifiedBefore') and witness.get('hwndVerifiedAfter'), 'Native editor HWND ownership changed'
    assert snapshot.get('boundsDpiContext') == 'per-monitor-v2' and witness.get('boundsDpiContextRestored'), 'Rendered bounds require a verified scoped physical-pixel DPI context'
    assert snapshot.get('sameLiveFrameVerified') and snapshot.get('containerHwnd') == child, 'Actual UNO frame is outside the verified editor'
    binding = snapshot.get('nativeNotebookbarBinding', {})
    assert (binding.get('ownedPeerWidgetVerified') and binding.get('targetWidgetType') == 'TabControlUIObject'
            and binding.get('targetWidgetId') == 'ContextContainer' and binding.get('nextFocusMatchesTargetWidget')
            and binding.get('focusRestored') and binding.get('selectionUnchanged')), 'Actual notebookbar widget is not bound to the verified native editor'
    assert snapshot.get('truncated') is False, 'Native accessibility search exceeded its finite bound'
    outer = snapshot.get('rootRectangle', [])
    assert len(outer) == 4 and inside(outer, outer), 'Native editor rendered bounds are invalid'
    for container in snapshot.get('tabContainers', []):
        if container.get('role') != PAGE_TAB_LIST:
            continue
        if not (container.get('visible') is True and container.get('sameLiveParentVerified') is True
                and container.get('distinctLiveObjectsVerified') is True
                and container.get('indexReadbackVerified') is True and inside(container.get('rectangle'), outer)):
            continue
        path = container.get('indexPath')
        if not isinstance(path, list) or not path or any(type(value) is not int or value < 0 for value in path):
            continue
        labels, indices = {}, set()
        for tab in container.get('tabs', []):
            if tab.get('role') != PAGE_TAB or tab.get('visible') is not True:
                continue
            # VCL keeps contextual pages alive and may report SHOWING even
            # when GetTabBounds is empty. Only actually rendered tabs qualify.
            if not inside(tab.get('rectangle'), outer):
                continue
            index, tab_path = tab.get('index'), tab.get('indexPath')
            assert type(index) is int and index >= 0 and index not in indices, 'Distinct native tabs require distinct actual child indices'
            indices.add(index)
            assert tab.get('parentIndexPath') == path and tab_path == path + [index], 'Native tabs must share the actual live tab-list parent'
            assert tab.get('liveParentVerified') and tab.get('liveIndexReadbackVerified'), 'Native tab identity was not verified against its live parent'
            label = normalize_label(tab.get('name', ''))
            assert label not in labels, 'Native tab labels are ambiguous within one actual tab list'
            labels[label] = tab
        if {'홈', '삽입'} <= labels.keys():
            return dict(koreanUiVerified=True, tabbedUiVerified=True,
                        evidenceProvider='live-native-VCL-accessibility',
                        osScreenReaderExposureCertified=False,
                        koreanTabLabels=['삽입', '홈'], nativeTabContainer=container,
                        tabControls=[labels[name] for name in ('삽입', '홈')])
    raise AssertionError('Native Office must expose Korean Home and Insert PAGE_TAB objects in one actual PAGE_TAB_LIST')


def _owned_process(child, pid, expected_creation, expected_image):
    from startup_smoke import EngineProcessWitness
    from windows_smoke import Windows
    api, process = Windows(), EngineProcessWitness(pid)
    try:
        assert process.creation_time == expected_creation and not process.exited(0), 'Owned engine process identity changed'
        assert api.user.IsWindow(child) and api.pid(child) == pid, 'Embedded HWND belongs to another engine'
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        query = kernel.QueryFullProcessImageNameW
        query.argtypes, query.restype = (W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)), W.BOOL
        capacity = W.DWORD(32768)
        image = ctypes.create_unicode_buffer(capacity.value)
        if not query(process.handle, 0, image, ctypes.byref(capacity)):
            raise ctypes.WinError(ctypes.get_last_error())
        assert os.path.normcase(str(Path(image.value).resolve(strict=True))) == os.path.normcase(str(Path(expected_image).resolve(strict=True))), 'Owned engine executable is outside the pinned runtime'
        return api, process
    except Exception:
        process.close()
        raise


def _command_line(process):
    """Query only the retained exact process; never enumerate other processes."""
    class UnicodeString(ctypes.Structure):
        _fields_ = [('Length', ctypes.c_ushort), ('MaximumLength', ctypes.c_ushort),
                    ('Buffer', ctypes.c_void_p)]
    query = ctypes.WinDLL('ntdll').NtQueryInformationProcess
    query.argtypes = (W.HANDLE, W.ULONG, ctypes.c_void_p, W.ULONG, ctypes.POINTER(W.ULONG))
    query.restype = ctypes.c_long
    required = W.ULONG()
    query(process.handle, 60, None, 0, ctypes.byref(required))  # ProcessCommandLineInformation.
    assert ctypes.sizeof(UnicodeString) < required.value <= 131072, 'Native process command-line size is invalid'
    buffer = ctypes.create_string_buffer(required.value)
    status = query(process.handle, 60, buffer, len(buffer), ctypes.byref(required))
    assert status >= 0, 'Native owned-process command-line query failed'
    value = UnicodeString.from_buffer(buffer)
    base, address, length = ctypes.addressof(buffer), int(value.Buffer or 0), int(value.Length)
    assert length % 2 == 0 and 0 < length <= value.MaximumLength <= len(buffer), 'Native command-line Unicode descriptor is invalid'
    assert base + ctypes.sizeof(UnicodeString) <= address <= base + len(buffer) - length, 'Native command-line pointer is outside its allocated buffer'
    command = ctypes.string_at(address, length).decode('utf-16-le', errors='strict')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    parse = shell.CommandLineToArgvW
    parse.argtypes, parse.restype = (W.LPCWSTR, ctypes.POINTER(ctypes.c_int)), ctypes.POINTER(W.LPWSTR)
    count = ctypes.c_int()
    arguments = parse(command, ctypes.byref(count))
    if not arguments:
        raise ctypes.WinError(ctypes.get_last_error())
    free = ctypes.WinDLL('kernel32').LocalFree
    free.argtypes, free.restype = (ctypes.c_void_p,), ctypes.c_void_p
    try:
        assert 1 <= count.value <= 64, 'Owned engine argument count is invalid'
        return [arguments[index] for index in range(count.value)]
    finally:
        free(arguments)


def capture_bounded(suite, child, pid, creation_time, module, destination):
    expected_image = suite / 'Office/program/soffice.bin'
    api, retained = _owned_process(child, pid, creation_time, expected_image)
    primary = child_failure = None
    try:
        pipe = private_pipe(_command_line(retained))
        request = dict(childHwnd=child, officePid=pid, creationTime=creation_time,
                       expectedImage=str(expected_image), module=module, pipe=pipe,
                       snapshot=str(destination))
        result = subprocess.run([str(suite/'Office/program/python.exe'), str(Path(__file__).resolve()), '--collect-live'],
                                input=json.dumps(request), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, encoding='utf-8', errors='replace',
                                timeout=45, shell=False)
        try:
            assert result.returncode == 0, 'Owned native accessibility collector failed: '
        except AssertionError as exc:
            primary = exc
            try:
                # This is the same retained-generation/HWND join as success.
                # A failed join only disqualifies optional child metadata.
                assert not retained.exited(0) and api.user.IsWindow(child) and api.pid(child) == pid, 'Owned engine changed during accessibility collection'
                child_failure = _decode_child_failure(result.stdout, request)
            except Exception:
                pass
            raise
        assert not retained.exited(0) and api.user.IsWindow(child) and api.pid(child) == pid, 'Owned engine changed during accessibility collection'
        snapshot = json.loads(destination.read_text(encoding='utf-8'))
        snapshot['witness']['retainedProcessHandle'] = True
        destination.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
        return snapshot
    finally:
        retained.close()
        if primary is not None and child_failure is not None:
            vars(primary)['_opengeul_native_accessibility_failure'] = child_failure


def _rectangle(context):
    point, size = context.getLocationOnScreen(), context.getSize()
    return [int(point.X), int(point.Y), int(point.X + size.Width), int(point.Y + size.Height)]


def _showing(context):
    states = int(context.getAccessibleStateSet())
    return bool(states & VISIBLE and states & SHOWING)


def _physical_window_rectangle(api, child):
    """Query physical pixels while changing only this collector thread's scope."""
    change = api.user.SetThreadDpiAwarenessContext
    change.argtypes, change.restype = (ctypes.c_void_p,), ctypes.c_void_p
    current = api.user.GetThreadDpiAwarenessContext
    current.argtypes, current.restype = (), ctypes.c_void_p
    equal = api.user.AreDpiAwarenessContextsEqual
    equal.argtypes, equal.restype = (ctypes.c_void_p, ctypes.c_void_p), W.BOOL
    physical = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.
    previous = change(physical)
    assert previous, 'Collector thread physical-pixel DPI scope could not be entered'
    try:
        assert equal(current(), physical), 'Collector thread did not enter per-monitor-v2 DPI scope'
        rectangle = W.RECT()
        api.user.GetWindowRect.argtypes = (W.HWND, ctypes.POINTER(W.RECT))
        api.user.GetWindowRect.restype = W.BOOL
        assert api.user.GetWindowRect(child, ctypes.byref(rectangle)), 'Owned native editor bounds are unavailable'
        return [rectangle.left, rectangle.top, rectangle.right, rectangle.bottom]
    finally:
        assert change(previous), 'Collector thread DPI scope could not be restored'
        assert equal(current(), previous), 'Collector thread DPI context restoration was not verified'


def _native_notebookbar(context, frame, peer, diagnostic):
    """Reach the real sibling widget through public UITest and focus events.

    XUIObject.equals compares the underlying VCL window pointer. The public
    FocusEvent.NextFocus carries that same window's actual XWindowPeer; its
    XAccessible then supplies real native tab roles, parents and page indices.
    """
    import unohelper
    from com.sun.star.awt import XFocusListener
    ui = context.ServiceManager.createInstanceWithContext('com.sun.star.ui.test.UITest', context)
    owner = ui.getWindow(peer)
    assert owner.equals(ui.getWindow(frame.getContainerWindow())), 'UITest owner differs from the verified frame peer'
    target = owner.getChild('ContextContainer')
    target_state = {item.Name: item.Value for item in target.getState()}
    assert target.getType() == 'TabControlUIObject' and target_state['ID'] == 'ContextContainer', 'Actual notebookbar is not the expected native TabControl'
    assert target_state['Visible'] == 'true' and target_state['ReallyVisible'] == 'true', 'Native notebookbar widget is not rendered'
    original = ui.getFocusWindow()
    component = frame.getComponentWindow()
    assert component is not None, 'Owned native document component window is missing'
    events, listeners, windows = [], [], []

    class Listener(unohelper.Base, XFocusListener):
        def focusGained(self, event):
            pass

        def focusLost(self, event):
            if event.NextFocus is not None:
                events.append(event.NextFocus)

        def disposing(self, event):
            pass

    listener = Listener()
    toolkit = context.ServiceManager.createInstanceWithContext('com.sun.star.awt.Toolkit', context)
    try:
        pending = [peer, component]
        while pending:
            window = pending.pop()
            if any(window == earlier for earlier in windows):
                continue
            windows.append(window)
            assert len(windows) <= 128, 'Owned native window focus census exceeded its finite bound'
            window.addFocusListener(listener)
            listeners.append(window)
            try:
                children = window.getWindows()
            except AttributeError:
                children = ()
            pending.extend(children)
        toolkit.addFocusListener(listener)
    except Exception:
        for window in listeners:
            try:
                window.removeFocusListener(listener)
            except Exception:
                pass  # Preserve the registration failure; no focus action ran.
        raise
    evidence = dict(targetType=str(target.getType()), targetState=target_state,
                    ownedWindowListenerCount=len(windows), nextFocusCandidates=[])
    matched = binding = None
    try:
        component.setFocus()
        target.executeAction('FOCUS', ())
        deadline = time.monotonic() + 3
        seen = 0
        while time.monotonic() < deadline and matched is None:
            while seen < len(events):
                candidate = events[seen]
                seen += 1
                widget = ui.getWindow(candidate)
                equal = bool(widget.equals(target))
                state = {item.Name: item.Value for item in widget.getState()}
                evidence['nextFocusCandidates'].append(dict(widgetType=str(widget.getType()), widgetState=state,
                                                            equalsNativeNotebookbar=equal))
                if equal:
                    matched = candidate
                    break
            if matched is None:
                time.sleep(0.02)
        evidence['focusedWidgetMatchesTarget'] = bool(ui.getFocusWindow().equals(target))
        assert matched is not None and evidence['focusedWidgetMatchesTarget'], 'No actual notebookbar XWindowPeer was witnessed in native focus events'
        accessible = matched.getProperty('XAccessible')
        assert int(accessible.getAccessibleContext().getAccessibleRole()) == PAGE_TAB_LIST, 'Actual focused notebookbar does not expose the native PAGE_TAB_LIST role'
        assert ui.getWindow(matched).equals(target), 'Native notebookbar widget identity changed'
        parent = accessible.getAccessibleContext().getAccessibleParent()
        assert parent is not None, 'Native notebookbar has no actual live accessible parent'
        chain, current, held = [], accessible, [accessible]
        while True:
            current_context = current.getAccessibleContext()
            parent_object = current_context.getAccessibleParent()
            if parent_object is None:
                break
            index = int(current_context.getAccessibleIndexInParent())
            assert index >= 0 and parent_object.getAccessibleContext().getAccessibleChild(index) == current, 'Actual notebookbar ancestor index round trip failed'
            assert not any(parent_object == earlier for earlier in held), 'Native notebookbar ancestor identity cycle'
            chain.append(index)
            held.append(parent_object)
            assert len(chain) <= 32, 'Native notebookbar parent chain exceeded its finite bound'
            current = parent_object
        binding = dict(ownedPeerWidgetVerified=True, targetWidgetType='TabControlUIObject',
                       targetWidgetId='ContextContainer', nextFocusMatchesTargetWidget=True,
                       focusRestored=False, selectionUnchanged=False)
        return accessible, list(reversed(chain)), parent, binding
    finally:
        cleanup_errors = []
        try:
            toolkit.removeFocusListener(listener)
        except Exception as exc:
            cleanup_errors.append('Toolkit listener removal: ' + type(exc).__name__)
        for window in listeners:
            try:
                window.removeFocusListener(listener)
            except Exception as exc:
                cleanup_errors.append('Window listener removal: ' + type(exc).__name__)
        try:
            original.executeAction('FOCUS', ())
            evidence['focusRestored'] = bool(ui.getFocusWindow().equals(original))
            final_state = {item.Name: item.Value for item in target.getState()}
            evidence['selectionUnchanged'] = final_state['CurrPagePos'] == target_state['CurrPagePos']
        except Exception as exc:
            cleanup_errors.append('Focus restoration: ' + type(exc).__name__)
        evidence['cleanupErrors'] = cleanup_errors
        diagnostic.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        assert not cleanup_errors, 'Native focus observer cleanup failed: ' + str(cleanup_errors)
        assert evidence.get('focusRestored'), 'Original native focus was not restored'
        assert evidence.get('selectionUnchanged'), 'Read-only notebookbar observation changed the selected tab'
        if binding is not None:
            binding.update(focusRestored=True, selectionUnchanged=True)


def collect_live(request, diagnostic=None):
    import uno
    child, pid = request['childHwnd'], request['officePid']
    api, retained = _owned_process(child, pid, request['creationTime'], request['expectedImage'])
    if diagnostic is not None: diagnostic['ownershipStage'] = 1
    try:
        assert re.fullmatch(r'OpenGeul_[0-9a-f]{32}', request['pipe']), 'Private accessibility transport is invalid'
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver', local)
        try:
            context = resolver.resolve('uno:pipe,name=' + request['pipe'] + ';urp;StarOffice.ComponentContext')
        except Exception as exc:
            raise RuntimeError('Owned accessibility connection failed: ' + type(exc).__name__) from None
        desktop = context.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop', context)
        frames, matches = desktop.getFrames(), []
        assert frames.getCount() <= 8, 'Owned accessibility engine has unexpected extra frames'
        for index in range(frames.getCount()):
            frame = frames.getByIndex(index)
            peer = frame.getContainerWindow()
            if peer is not None and int(peer.getWindowHandle((), 1)) == child:
                matches.append((frame, peer))
        assert len(matches) == 1, 'Exactly one actual Office frame must own the verified editor HWND'
        frame, peer = matches[0]
        controller = frame.getController()
        assert controller is not None and controller.getFrame() == frame, 'Loaded native controller belongs to another frame'
        service = MODULE_SERVICES[request['module']]
        assert controller.getModel().supportsService(service), 'Loaded native frame belongs to another module'
        if diagnostic is not None: diagnostic['ownershipStage'] = 2
        assert int(uno.getConstantByName(ROLE_NAMESPACE + '.PAGE_TAB')) == PAGE_TAB
        assert int(uno.getConstantByName(ROLE_NAMESPACE + '.PAGE_TAB_LIST')) == PAGE_TAB_LIST
        # Pinned public XVclWindowPeer test property returns the instantiated VCL
        # XAccessible. Its native border parent also owns the notebookbar sibling.
        peer_accessible = peer.getProperty('XAccessible')
        peer_context = peer_accessible.getAccessibleContext()
        peer_parent_absent = peer_context.getAccessibleParent() is None
        accessible, actual_path, actual_parent, notebookbar_binding = _native_notebookbar(
            context, frame, peer, Path(request['snapshot']).with_name(Path(request['snapshot']).stem + '-focus-diagnostic.json'))
        visited, tab_containers = [0], []
        skipped = {int(uno.getConstantByName(ROLE_NAMESPACE + '.' + role)) for role in
                   ('DOCUMENT', 'DOCUMENT_TEXT', 'DOCUMENT_SPREADSHEET', 'DOCUMENT_PRESENTATION',
                    'TABLE', 'TABLE_CELL', 'TREE', 'TREE_TABLE')}

        def visit(accessible, path, parent=None, ancestors=()):
            visited[0] += 1
            assert visited[0] <= 3000 and len(path) <= 32, 'Native control search exceeded its finite bound'
            assert not any(accessible == ancestor for ancestor in ancestors), 'Native accessible tree contains a live identity cycle'
            current = accessible.getAccessibleContext()
            role = int(current.getAccessibleRole())
            if role in skipped:
                return
            count = int(current.getAccessibleChildCount())
            assert 0 <= count <= 512, 'Native chrome container has an excessive child count'
            if role == PAGE_TAB_LIST:
                visited[0] += count
                assert visited[0] <= 3000, 'Native tab context count exceeded its finite bound'
                assert parent is not None and current.getAccessibleParent() == parent, 'Native tab list belongs to another live parent'
                assert int(current.getAccessibleIndexInParent()) == path[-1], 'Native tab-list index differs from its actual parent path'
                tabs, held = [], []
                for index in range(count):
                    tab = current.getAccessibleChild(index)
                    tab_context = tab.getAccessibleContext()
                    assert tab_context.getAccessibleParent() == accessible, 'Native tab belongs to another live tab-list parent'
                    assert int(tab_context.getAccessibleIndexInParent()) == index, 'Native tab index differs from its actual parent child'
                    assert not any(tab == earlier for earlier in held), 'Native tab children reuse the same live object'
                    assert current.getAccessibleChild(index) == tab, 'Native tab identity changed during its index readback'
                    held.append(tab)
                    tabs.append(dict(name=str(tab_context.getAccessibleName()), role=int(tab_context.getAccessibleRole()),
                                     visible=_showing(tab_context), rectangle=_rectangle(tab_context), index=index,
                                     indexPath=path+[index], parentIndexPath=path,
                                     liveParentVerified=True, liveIndexReadbackVerified=True))
                # Recheck live objects while every sibling and parent reference
                # remains retained; numeric paths come from actual API indices.
                for index, tab in enumerate(held):
                    assert current.getAccessibleChild(index) == tab and tab.getAccessibleContext().getAccessibleParent() == accessible, 'Native tab identity or parent changed during capture'
                tab_containers.append(dict(role=role, name=str(current.getAccessibleName()), visible=_showing(current),
                                           rectangle=_rectangle(current), indexPath=path, tabs=tabs,
                                           sameLiveParentVerified=True, distinctLiveObjectsVerified=True,
                                           indexReadbackVerified=True))
                return  # Do not enumerate document content or each tab's toolbar.
            for index in range(count):
                visit(current.getAccessibleChild(index), path+[index], accessible, ancestors+(accessible,))

        visit(accessible, actual_path, actual_parent)
        assert int(peer.getWindowHandle((), 1)) == child and controller.getFrame() == frame, 'Native frame changed during accessibility capture'
        assert not retained.exited(0) and api.user.IsWindow(child) and api.pid(child) == pid, 'Owned editor changed during accessibility capture'
        rectangle = _physical_window_rectangle(api, child)
        snapshot = dict(schemaVersion=1, kind='owned-native-vcl-accessibility', roleNamespace=ROLE_NAMESPACE,
                        roleConstants={'PAGE_TAB': PAGE_TAB, 'PAGE_TAB_LIST': PAGE_TAB_LIST}, officePid=pid,
                        childHwnd=child, containerHwnd=child, module=request['module'], loadedModuleService=service,
                        officeCreationTime=request['creationTime'], pipeNameSha256=hashlib.sha256(request['pipe'].encode('ascii')).hexdigest(),
                        rootRectangle=rectangle, boundsDpiContext='per-monitor-v2',
                        sameLiveFrameVerified=True, ownedPeerAccessibleParentAbsent=peer_parent_absent,
                        nativeNotebookbarBinding=notebookbar_binding,
                        nativeAccessibleContextCount=visited[0], truncated=False, tabContainers=tab_containers,
                        osScreenReaderExposureCertified=False,
                        witness=dict(retainedProcessHandle=True, imageVerified=True, creationTimeVerified=True,
                                     hwndVerifiedBefore=True, hwndVerifiedAfter=True, boundsDpiContextRestored=True))
        with Path(request['snapshot']).open('x', encoding='utf-8') as stream:
            json.dump(snapshot, stream, ensure_ascii=False, indent=2, allow_nan=False)
    finally:
        retained.close()


def _collect_main(request):
    diagnostic = dict(ownershipStage=0)
    try:
        collect_live(request, diagnostic)
    except Exception as exc:
        # All existing focus/listener/DPI/retained-handle finally blocks have
        # already run. Never read text, traceback formatting or UNO properties.
        try:
            from numeric_notice import (MODULES, notices_enabled, capture_failure_code,
                                        capture_failure_frames)
            if notices_enabled():
                value = _validate_child_failure(dict(schemaVersion=1,
                    officePid=request['officePid'], officeCreationTime=request['creationTime'],
                    childHwnd=request['childHwnd'], moduleCode=MODULES[request['module']],
                    ownershipStage=diagnostic['ownershipStage'], failure=capture_failure_code(exc),
                    ownedFrames=capture_failure_frames(exc)), request)
                message = json.dumps(value, separators=(',', ':'), allow_nan=False)
                if len(message.encode('utf-8'))+1 <= 1024:
                    sys.stdout.write(message+'\n')
                    sys.stdout.flush()
        except Exception:
            pass  # A partial/broken output is not retried and cannot hide failure.
        return 1
    return 0


if __name__ == '__main__':
    assert os.name == 'nt' and __debug__ and sys.argv[1:] == ['--collect-live'], 'Actual Windows native collector execution is required'
    raise SystemExit(_collect_main(json.loads(sys.stdin.read(32768))))
