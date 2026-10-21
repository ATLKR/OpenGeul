"""Thread-scoped Win64 ASCII queue observer controller.

Mapping/controller handles are distinct from the target DLL's independently
opened view. Stop means future recording disabled; neither stop nor Unhook is
evidence of remote callback quiescence, view retirement or DLL unload.
"""
from __future__ import annotations

import ctypes as C
from pathlib import Path
import time
import uuid

from ascii_message_protocol import State, Event, MAGIC, VERSION, CAPACITY
from counted_editor_shortcuts import (CountedEditorShortcuts, NativeShortcutProbe,
    join_shortcut_generation, _same_image)


def _error():
    return getattr(C, 'get_last_error', lambda: 0)()


def _clear_error():
    getattr(C, 'set_last_error', lambda value: None)(0)


class MessageTransport:
    """One private mapping and exactly two thread-specific hook installations."""
    def __init__(self, user, kernel, library, target, creation_time, receipt,
                 deadline, clock, identity, *, nonce=None):
        self.user, self.kernel, self.dll = user, kernel, library
        self.target, self.creation = dict(target), creation_time
        self.record, self.deadline, self.clock, self.identity = receipt, deadline, clock, identity
        self.nonce = nonce if nonce is not None else uuid.uuid4().int & 0xffffffffffffffff
        assert type(self.nonce) is int and 0 < self.nonce <= 0xffffffffffffffff
        self.mapping = self.view = self.state = None
        self.hooks = []; self.closed = False; self.cursor = 0
        self.start_message = self.stop_message = None
        for name in ('GetCurrentProcessId','GetCurrentThreadId'):
            function = getattr(kernel,name)
            function.argtypes, function.restype = (), C.c_uint32
        self.controller_pid = int(kernel.GetCurrentProcessId())
        self.controller_tid = int(kernel.GetCurrentThreadId())
        assert self.controller_pid != target['pid'] and self.controller_tid != target['tid'], 'Observer requires a distinct controller process/thread'
        H, D, B, Q, S = C.c_void_p, C.c_uint32, C.c_int32, C.c_uint64, C.c_int64
        for lib, name, arguments, result in (
            (kernel, 'CreateFileMappingW', (H,H,D,D,D,C.c_wchar_p), H),
            (kernel, 'MapViewOfFile', (H,D,D,D,C.c_size_t), H),
            (kernel, 'UnmapViewOfFile', (H,), B), (kernel, 'CloseHandle', (H,), B),
            (kernel, 'FreeLibrary', (H,), B),
            (user, 'RegisterWindowMessageW', (C.c_wchar_p,), D),
            (user, 'SetWindowsHookExW', (C.c_int,H,H,D), H),
            (user, 'UnhookWindowsHookEx', (H,), B),
            (user, 'SendMessageTimeoutW', (H,D,Q,S,D,D,C.POINTER(Q)), S),
            (library, 'ReadWord', (C.POINTER(D),), D),
            (library, 'PublishWord', (C.POINTER(D),D), None),
            (library, 'StateSize', (), D), (library, 'EventSize', (), D),
            (library, 'EventsOffset', (), D)):
            function = getattr(lib, name); function.argtypes, function.restype = arguments, result
        assert (library.StateSize(), library.EventSize(), library.EventsOffset()) == \
            (C.sizeof(State), C.sizeof(Event), State.events.offset), 'Native ASCII observer ABI differs'
        receipt['transport'] = dict(controllerPid=self.controller_pid, controllerTid=self.controller_tid,
            nonce=self.nonce, hookAttempts=[], controls=[], remoteCallbackQuiescenceProved=False)

    def _budget(self):
        remaining = self.deadline - self.clock()
        assert remaining > 0, 'ASCII observer transport deadline expired'
        return remaining

    def _word(self, name):
        return C.cast(self.view + getattr(State, name).offset, C.POINTER(C.c_uint32))

    def _read(self, name):
        return int(self.dll.ReadWord(self._word(name)))

    def _publish(self, name, value):
        self.dll.PublishWord(self._word(name), value)

    def _header(self):
        assert self.state is not None, 'ASCII observer mapping is not admitted'
        assert (self.state.magic, self.state.version, self.state.stateSize, self.state.eventSize, self.state.capacity) == \
            (MAGIC, VERSION, C.sizeof(State), C.sizeof(Event), CAPACITY), 'ASCII observer ABI changed'
        expected = (self.target['pid'], self.target['tid'], self.target['hwnd'], self.target['layout'],
                    self.creation, self.controller_pid, self.nonce, self.start_message, self.stop_message)
        observed = tuple(getattr(self.state, key) for key in ('pid','tid','hwnd','layout','engineCreationTime',
            'controllerPid','nonce','startMessage','stopMessage'))
        assert observed == expected, 'ASCII observer immutable target/header changed'
        assert self._read('overflow') == self._read('status') == 0, 'ASCII observer native overflow/status failed'
        count = self._read('count')
        assert 0 <= count <= CAPACITY, 'ASCII observer native count exceeded its bound'
        return count

    def _control(self, message):
        self._budget(); self.identity(); self._budget()
        timeout = min(5000, int(self._budget() * 1000))
        assert timeout > 0, 'ASCII observer deadline has no complete control millisecond'
        row = dict(message=message, hwnd=self.target['hwnd'], pid=self.target['pid'],
            tid=self.target['tid'], creationTime=self.creation, startedAt=self.clock(),
            flags=0x22, timeoutMilliseconds=timeout)
        self.record['transport']['controls'].append(row)
        result = C.c_uint64()
        _clear_error()
        assert row['startedAt'] < self.deadline, 'ASCII observer control deadline expired at intent'
        row['timeoutMilliseconds'] = min(row['timeoutMilliseconds'], int(self._budget() * 1000))
        assert row['timeoutMilliseconds'] > 0, 'ASCII observer deadline has no complete control millisecond'
        value = self.user.SendMessageTimeoutW(self.target['hwnd'], message, self.controller_pid,
            C.c_int64(self.nonce).value, row['flags'], row['timeoutMilliseconds'], C.byref(result))
        error = _error()
        row.update(nativeReturn=int(value or 0), lastError=error, messageResult=result.value, returnedAt=self.clock())
        assert value, 'ASCII observer inert control failed (lastError=' + str(error) + ')'
        self._budget()

    def start(self):
        self._budget()
        self.start_message = int(self.user.RegisterWindowMessageW('OpenGeul.AsciiObserver.Start.v1'))
        self._budget()
        self.stop_message = int(self.user.RegisterWindowMessageW('OpenGeul.AsciiObserver.Stop.v1'))
        assert 0xc000 <= self.start_message <= 0xffff and 0xc000 <= self.stop_message <= 0xffff \
            and self.start_message != self.stop_message, 'Observer control message registration failed'
        name = f'Local\\OpenGeulAscii_{self.controller_pid}_{self.nonce:016x}'
        _clear_error()
        self._budget()
        self.mapping = self.kernel.CreateFileMappingW(C.c_void_p(-1), None, 4, 0, C.sizeof(State), name)
        error = _error()
        self.record['transport']['mapping'] = dict(name=name, handle=int(self.mapping or 0), lastError=error)
        if not self.mapping or error == 183: raise OSError(error, 'Private ASCII observer mapping admission failed')
        self._budget()
        self.view = self.kernel.MapViewOfFile(self.mapping, 0xf001f, 0, 0, C.sizeof(State))
        if not self.view: raise OSError(_error(), 'MapViewOfFile ASCII observer failed')
        self.state = State.from_address(self.view)
        C.memset(self.view, 0, C.sizeof(State))
        for key, value in dict(magic=MAGIC, version=VERSION, stateSize=C.sizeof(State),
            eventSize=C.sizeof(Event), capacity=CAPACITY, pid=self.target['pid'], tid=self.target['tid'],
            controllerPid=self.controller_pid, startMessage=self.start_message, stopMessage=self.stop_message,
            nonce=self.nonce, hwnd=self.target['hwnd'], engineCreationTime=self.creation, layout=self.target['layout']).items():
            setattr(self.state, key, value)
        self._publish('command', 1)
        for kind, export in ((4, 'HookCall'), (3, 'HookGet')):
            self._budget(); self.identity(); self._budget()
            row = dict(kind=kind, threadId=self.target['tid'], attemptedAt=self.clock())
            self.record['transport']['hookAttempts'].append(row)
            function = C.cast(getattr(self.dll, export), C.c_void_p)
            assert row['attemptedAt'] < self.deadline, 'ASCII observer hook deadline expired at intent'
            self._budget()
            handle = self.user.SetWindowsHookExW(kind, function, self.dll._handle, self.target['tid'])
            error = _error()
            if handle: self.hooks.append(int(handle))
            row.update(handle=int(handle or 0), lastError=error, returnedAt=self.clock())
            if not handle: raise OSError(error, 'SetWindowsHookExW ASCII observer failed')
            self._budget()
        self._control(self.start_message)
        self._header()
        assert self._read('recording') == self._read('ack') == 1, 'ASCII observer start was not acknowledged'

    def arm(self, index):
        self._budget()
        count = self._header()
        assert count == self.cursor, 'ASCII observer baseline has pending/unread messages'
        assert self._read('recording') == self._read('ack') == 1, 'ASCII observer is not recording'
        self._publish('armedIndex', index)
        self._publish('armedEpoch', index + 1)
        self._budget()
        return count

    def read_events(self, after):
        self._budget()
        count = self._header()
        assert type(after) is int and 0 <= after <= count, 'ASCII observer read baseline differs'
        rows = []
        for index in range(after, count):
            self._budget()
            address = self.view + State.events.offset + index * C.sizeof(Event)
            commit = C.cast(address, C.POINTER(C.c_uint32))
            sequence = int(self.dll.ReadWord(commit))
            if not sequence: break
            assert sequence == index + 1, 'ASCII observer commit sequence changed'
            raw = C.string_at(address, C.sizeof(Event))
            assert int(self.dll.ReadWord(commit)) == sequence, 'ASCII observer commit changed during copy'
            row = Event.from_buffer_copy(raw)
            assert row.sequence == sequence and row.reserved == 0, 'ASCII observer committed row changed'
            rows.append({key: int(getattr(row, key)) for key, _ in Event._fields_ if key != 'reserved'})
        self._header(); self._budget()
        if rows: self.cursor = rows[-1]['sequence']
        return rows

    def can_stop(self):
        return bool(self.hooks and self.view and self.start_message)

    def stop(self):
        self._budget(); self.identity(); self._header()
        self._publish('command', 2)
        self._control(self.stop_message)
        assert self._read('recording') == 0 and self._read('stopAck') == 2, 'ASCII observer stop was not acknowledged'
        row = dict(recordingStopped=True, sampledEventCount=self._read('count'),
            sampledActiveCallbacks=self._read('activeCallbacks'), eventCountFinal=False,
            remoteCallbackQuiescenceProved=False, targetViewRetirementProved=False)
        self.record['transport']['stop'] = row
        self._budget()
        return row

    def close(self):
        if self.closed: return self.record['transportCleanup']
        self.closed = True
        row = dict(unhookAttempts=0, unhooks=[], errors=[], controllerResourcesReleased=False,
            remoteCallbackQuiescenceProved=False, targetViewRetirementProved=False)
        self.record['transportCleanup'] = row
        for handle in self.hooks:
            row['unhookAttempts'] += 1
            try:
                value = bool(self.user.UnhookWindowsHookEx(handle))
                error = _error(); row['unhooks'].append(dict(handle=handle, nativeReturn=value, lastError=error))
                if not value: raise OSError(error, 'UnhookWindowsHookEx ASCII observer failed')
            except BaseException as exc:
                row['errors'].append(type(exc).__name__ + ': ' + str(exc))
        for name, handle, function in (('view', self.view, self.kernel.UnmapViewOfFile),
            ('mapping', self.mapping, self.kernel.CloseHandle), ('library', self.dll._handle, self.kernel.FreeLibrary)):
            if handle:
                try:
                    value = bool(function(handle)); error = _error()
                    row[name] = dict(handle=int(handle), nativeReturn=value, lastError=error)
                    if not value: raise OSError(error, 'ASCII observer ' + name + ' release failed')
                except BaseException as exc:
                    row['errors'].append(type(exc).__name__ + ': ' + str(exc))
        row['controllerResourcesReleased'] = not row['errors']
        if row['errors']: raise OSError('; '.join(row['errors']))
        return row


class NativeAsciiProbe:
    """New retained native HANDLE joined to the caller's exact native binding.

The binding may originate in an earlier reader or first-admission keyboard
session. This class claims only that measured native generation join; it never
manufactures an earlier model-reader observation or reuses a closed HANDLE.
"""
    # Reuse the reviewed strict native scope/capture policy unchanged. These
    # methods contain observations only; no shortcut delivery method is used.
    _observe_guard = CountedEditorShortcuts._observe_guard
    _validate_guard = CountedEditorShortcuts._validate_guard
    _guard = CountedEditorShortcuts._guard

    def __init__(self, api, process, binding, prepared, receipt, deadline, clock):
        self.api, self.process, self.binding = api, process, dict(binding)
        self.prepared, self.receipt = prepared, receipt
        self.deadline, self.clock = deadline, clock
        self.handle = self.original_shell = self.original_engine = None
        self.thread = self.lock_state = self.target = None
        self.probe = self.transport = self.dll = None
        self.closed = False

    def _budget(self):
        assert self.clock() < self.deadline, 'ASCII native observer deadline expired'

    def _session(self, pid):
        session = C.c_uint32()
        function = self.probe.kernel.ProcessIdToSessionId
        function.argtypes, function.restype = (C.c_uint32, C.POINTER(C.c_uint32)), C.c_int32
        assert function(pid, C.byref(session)), 'ASCII observer native session query failed'
        return session.value

    def admit(self):
        import native_suite_architecture as architecture
        from ascii_message_preparation import require_prepared_library
        p, b = self.process, self.binding
        self._budget()
        suite = Path(p.opengeul_suite_root)
        assert suite.is_absolute() and isinstance(p.args, (list, tuple))
        assert _same_image(p.args[0], suite / 'OpenGeul.Office.exe'), 'Original Suite command image changed'
        assert type(p.pid) is int and p.pid > 0 and int(p._handle) > 0
        assert b['shellPid'] == p.pid and b['suiteHwnd'] == b['rootHwnd']
        for name in ('shellCreationTime','officePid','officeCreationTime','suiteHwnd','parentHwnd','childHwnd'):
            assert type(b[name]) is int and b[name] > 0, 'Invalid earlier ASCII native binding'
        assert _same_image(b['expectedImage'], suite / 'Office/program/soffice.bin')
        self.probe = NativeShortcutProbe(self.deadline, self.clock)
        shell = self.probe.process_snapshot(p)
        expected = (p.pid,int(p._handle),str((suite/'OpenGeul.Office.exe').resolve()),b['shellCreationTime'],258)
        assert tuple(shell[key] for key in ('pid','handleValue','image','creationTime','waitResult')) == expected
        assert p.opengeul_activation_binding == expected, 'Original retained shell activation changed'
        self.original_shell = shell
        self._budget()
        self.handle = self.probe.open_engine(b['officePid'])
        assert type(self.handle) is int and self.handle > 0, 'ASCII engine HANDLE admission failed'
        self.receipt['engineHandleAdmittedAt'] = self.clock()
        self.receipt['engineAdmissionBasis'] = 'new query+sync HANDLE joined to earlier native generation, without an earlier reader claim'
        self._budget()
        engine = self.probe.engine_snapshot(self.handle)
        assert (engine['pid'],engine['handleValue'],engine['creationTime'],engine['waitResult']) == \
            (b['officePid'],self.handle,b['officeCreationTime'],258), 'Earlier native engine generation changed'
        assert _same_image(engine['image'], b['expectedImage'])
        self.original_engine = engine
        self.receipt['priorShortcutGeneration'] = join_shortcut_generation(p,b['parentHwnd'],b['childHwnd'],engine)
        old = getattr(p,'opengeul_editor_click_generations',{}).get((b['parentHwnd'],b['childHwnd'],b['officePid']))
        if old is not None:
            assert (old[0],old[2]) == (engine['pid'],engine['creationTime']) and _same_image(old[1],engine['image'])
        self.receipt.update(originalShell=dict(shell),originalEngine=dict(engine))
        selected = self.prepared['architecture']
        self.receipt['nativeArchitectures'] = {
            name: architecture.validate_native_architecture(architecture.observe_native_architecture(handle),selected)
            for name,handle in (('controller',None),('shell',int(p._handle)),('engine',self.handle))}
        self.controller_pid = int(self.probe.kernel.GetCurrentProcessId())
        self.sessions = {name:self._session(pid) for name,pid in
            (('controller',self.controller_pid),('shell',p.pid),('engine',engine['pid']))}
        assert len(set(self.sessions.values())) == 1, 'ASCII observer crosses native sessions'
        self.receipt['nativeSessions'] = dict(self.sessions)
        scope = self._guard()['scope']
        focus = scope['focus']
        self.target = dict(pid=engine['pid'],tid=focus['threadId'],hwnd=focus['hwnd'],layout=0x04090409)
        assert self.target['tid'] == self.thread, 'Focused ASCII window is on a different editor thread'
        self._budget()
        library_path = require_prepared_library(self.prepared,architecture=selected)
        self._budget()
        # Bind cleanup before acquiring an HMODULE: the transport constructor
        # may fail before its own signatures are initialized.
        self.probe.kernel.FreeLibrary.argtypes = (C.c_void_p,)
        self.probe.kernel.FreeLibrary.restype = C.c_int32
        self.dll = C.WinDLL(str(library_path),use_last_error=True)
        self.transport = MessageTransport(self.probe.user,self.probe.kernel,self.dll,self.target,
            engine['creationTime'],self.receipt,self.deadline,self.clock,self._identity)
        self._budget()
        return dict(self.target)

    def _identity(self):
        self._budget()
        assert self.probe.process_snapshot(self.process) == self.original_shell, 'Original ASCII shell generation changed'
        assert self.probe.engine_snapshot(self.handle) == self.original_engine, 'Original ASCII engine generation changed'
        window = self.api._focus_window(self.target['hwnd'])
        self.receipt['lastControlTargetObservation'] = window
        assert window['isWindow'] is True and (window['hwnd'],window['pid'],window['threadId'],window['rootHwnd']) == \
            (self.target['hwnd'],self.target['pid'],self.target['tid'],self.binding['suiteHwnd']), 'Original ASCII control target changed'
        assert {name:self._session(pid) for name,pid in
            (('controller',self.controller_pid),('shell',self.process.pid),('engine',self.binding['officePid']))} == self.sessions
        self._budget()

    def guard(self):
        self._identity()
        scope = self._guard()['scope']
        focus = scope['focus']
        return dict(pid=focus['pid'],tid=focus['threadId'],hwnd=focus['hwnd'],layout=0x04090409)

    def start(self): self.transport.start()
    def arm(self,index): return self.transport.arm(index)
    def read_events(self,after): return self.transport.read_events(after)
    def can_stop(self): return self.transport is not None and self.transport.can_stop()
    def stop(self): return self.transport.stop()

    def close(self):
        if self.closed: return self.receipt['nativeCleanup']
        self.closed = True
        result = dict(controllerResourcesReleased=False,engineHandleReleased=self.handle is None,
            unhookAttempts=0,errors=[],remoteCallbackQuiescenceProved=False)
        self.receipt['nativeCleanup'] = result
        try:
            if self.transport is not None:
                try:
                    result.update(self.transport.close())
                finally:
                    result['unhookAttempts'] = self.receipt.get('transportCleanup',{}).get('unhookAttempts',0)
            elif self.dll is not None:
                assert self.probe.kernel.FreeLibrary(self.dll._handle), 'ASCII observer partial library release failed'
                result['controllerResourcesReleased'] = True
            else:
                result['controllerResourcesReleased'] = True
        except BaseException as exc:
            result['errors'].append(type(exc).__name__ + ': ' + str(exc))
        finally:
            if self.handle is not None:
                try:
                    result['engineHandleReleased'] = bool(self.probe.close_engine(self.handle))
                    assert result['engineHandleReleased'], 'ASCII observer engine HANDLE release failed'
                except BaseException as exc:
                    result['errors'].append(type(exc).__name__ + ': ' + str(exc))
        if result['errors']: raise OSError('; '.join(result['errors']))
        return result
