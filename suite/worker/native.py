"""Actual GUI UNO embedding. No headless or external-window fallback exists."""
import importlib
from pathlib import Path
import shutil
import tempfile
import time
import uuid

from dispatch import DispatchRouter, make_interceptor, make_interaction_handler
from session import WorkerError


class PrivateProfile:
    """Explicit cleanup only: losing stdin must never delete a live office profile."""
    def __init__(self):
        self.name = tempfile.mkdtemp(prefix='OpenGeul-office-')

    def cleanup(self):
        shutil.rmtree(self.name)


def connect_uno(uno, pipe, process, timeout=30, clock=time.monotonic, sleeper=time.sleep):
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver', local)
    deadline = clock() + timeout
    while clock() < deadline:
        if process.poll() is not None:
            raise WorkerError('engine_exited', 'Office 런타임이 시작 중 종료되었습니다.')
        try:
            return resolver.resolve('uno:pipe,name=' + pipe + ';urp;StarOffice.ComponentContext')
        except Exception:
            sleeper(0.1)
    raise WorkerError('connect_timeout', 'Office 런타임 연결 시간이 초과되었습니다.')


class UnoBackend:
    def __init__(self, runtime, process_factory=None, window_api=None, uno_loader=None, connector=None):
        self.runtime = Path(runtime)
        self.process_factory = process_factory
        self.window_api = window_api
        self.uno_loader = uno_loader or (lambda: importlib.import_module('uno'))
        self.connector = connector or connect_uno
        self.process = self.profile = self.document = self.desktop = self.frame = self.peer = None
        self.uno = None
        self.interceptor = None
        self.pipe = 'OpenGeul_' + uuid.uuid4().hex
        self.command_handler = lambda command: None

    def set_command_handler(self, handler):
        self.command_handler = handler

    def _start_runtime(self):
        program = self.runtime / 'program'
        if not all((program / name).is_file() for name in ('soffice.exe', 'python.exe')):
            raise WorkerError('runtime_missing', '포함된 Windows Office 런타임을 찾을 수 없습니다.')
        self.profile = PrivateProfile()
        argv = [str(program / 'soffice.exe'), '--invisible', '--nologo', '--nodefault', '--norestore',
                '--nofirststartwizard', '-env:UserInstallation=' + Path(self.profile.name).as_uri(),
                '--accept=pipe,name=' + self.pipe + ';urp;StarOffice.ServiceManager']
        if self.process_factory is None:
            from native_windows import OwnedOfficeProcess
            self.process_factory = OwnedOfficeProcess
        self.process = self.process_factory(argv, program)

    def _property(self, name, value):
        prop = self.uno.createUnoStruct('com.sun.star.beans.PropertyValue')
        prop.Name, prop.Value = name, value
        return prop

    def attach(self, hwnd, module, width, height, path):
        if self.window_api is None:
            from native_windows import WindowApi
            self.window_api = WindowApi()
        self.window_api.validate_parent(hwnd)
        try:
            self.uno = self.uno_loader()
        except ImportError as exc:
            raise WorkerError('uno_unavailable', 'Office에 포함된 program/python.exe로 작업자를 실행해 주세요.') from exc
        self._start_runtime()
        context = self.connector(self.uno, self.pipe, self.process)
        service = lambda name: context.ServiceManager.createInstanceWithContext(name, context)
        self.desktop = service('com.sun.star.frame.Desktop')
        toolkit = service('com.sun.star.awt.Toolkit')
        self.peer = toolkit.createSystemChild(self.uno.Any('hyper', hwnd), (), 1)
        if self.peer is None:
            raise WorkerError('attach_failed', 'Windows 내장 편집기 패널을 만들 수 없습니다.')
        self.frame = service('com.sun.star.frame.Frame')
        self.frame.initialize(self.peer)
        frame_name = 'OpenGeul_' + uuid.uuid4().hex
        self.frame.setName(frame_name)
        self.desktop.getFrames().append(self.frame)
        self.peer.setPosSize(0, 0, width, height, 15)
        self.interceptor = make_interceptor(self.command_handler)
        self.frame.registerDispatchProviderInterceptor(self.interceptor)
        interaction = make_interaction_handler()
        props = tuple(self._property(name, value) for name, value in (
            ('MacroExecutionMode', 0), ('UpdateDocMode', 0), ('ReadOnly', False),
            ('Hidden', False), ('PickListEntry', False), ('InteractionHandler', interaction)))
        url = path.as_uri() if path is not None else module['factory']
        self.document = self.desktop.loadComponentFromURL(url, frame_name, 4, props)
        if self.document is None:
            raise WorkerError('open_failed', '문서를 열 수 없습니다. 파일 형식과 암호 여부를 확인해 주세요.')
        child = int(self.peer.getWindowHandle((), 1))
        self.window_api.validate_child(child, hwnd)
        self.peer.setVisible(True)
        self.frame.activate()
        return {'parentHwnd': hwnd, 'childHwnd': child}

    def status(self):
        if self.process is not None and self.process.poll() is not None:
            raise WorkerError('engine_exited', 'Office 런타임이 종료되었습니다.')
        # Missing XModifiable is an error, never an assumption that the file is clean.
        return {'modified': bool(self.document.isModified()), 'title': str(self.document.getTitle())}

    def resize(self, width, height):
        self.peer.setPosSize(0, 0, width, height, 15)

    def save(self, path, filter_name):
        if path is None:
            self.document.store()
        else:
            props = (self._property('FilterName', filter_name), self._property('Overwrite', True),
                     self._property('InteractionHandler', make_interaction_handler()))
            self.document.storeAsURL(path.as_uri(), props)
        if self.document.isModified():
            raise WorkerError('save_failed', 'Office가 저장 완료를 확인하지 않았습니다.')

    def close(self, discard):
        if discard and self.process is not None and self.process.poll() is not None:
            self.document = None
            return
        modified = bool(self.document.isModified())
        if modified and not discard:
            raise WorkerError('close_cancelled', '저장되지 않은 변경 사항이 있습니다.')
        if discard:
            self.document.setModified(False)
        try:
            # False prevents transferring ownership on a veto/ongoing operation.
            self.document.close(False)
        except Exception:
            if modified:
                self.document.setModified(True)
            raise
        self.document = None

    def cleanup(self):
        if self.desktop is not None:
            try:
                self.desktop.terminate()
            except Exception:
                pass
        if self.process is not None:
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                # Keep the live profile when process death was not confirmed.
                return
            self.process.close()
            self.process = None
        self.document = self.desktop = self.frame = self.peer = self.interceptor = None
        if self.profile is not None:
            try:
                self.profile.cleanup()
                self.profile = None
            except OSError:
                pass
