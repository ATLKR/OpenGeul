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


def connect_uno(uno, pipe, process, timeout=90, clock=time.monotonic, sleeper=time.sleep):
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver', local)
    deadline = clock() + timeout
    last_error = None
    while clock() < deadline:
        if process.poll() is not None:
            raise WorkerError('engine_exited', 'Office 런타임이 시작 중 종료되었습니다.')
        try:
            return resolver.resolve('uno:pipe,name=' + pipe + ';urp;StarOffice.ComponentContext')
        except Exception as exc:
            last_error = exc
            sleeper(0.1)
    raise WorkerError('connect_timeout', 'Office 런타임 연결 시간이 초과되었습니다.') from last_error


def base_readiness(document, context=None):
    """Observe existing state only; never connect a database or start a JVM.

    DriverManager.getDriverByURL asks registered drivers' acceptsURL methods;
    it does not invoke connect (connectivity/source/manager/mdrivermanager.cxx).
    XJavaVM.isVMEnabled/isVMStarted only observe flags. getJavaVM would start it
    and is deliberately excluded (udkapi/com/sun/star/java/XJavaVM.idl).
    """
    readiness = {'state': 'unverified', 'dataSourceConfigured': None,
                 'connectionVerified': False, 'driverAvailable': None,
                 'javaRequired': None, 'javaAvailable': None,
                 'javaEnabled': None, 'javaStarted': None,
                 'fullyVerified': False,
                 'message': 'Base 데이터 원본과 Java 준비 상태를 확인하지 못했습니다.'}
    try:
        url = document.DataSource.getPropertyValue('URL')
        if not isinstance(url, str):
            return readiness
        readiness['dataSourceConfigured'] = bool(url.strip())
        if not url.strip():
            readiness.update(state='not_configured',
                             message='Base 데이터 원본이 설정되지 않았습니다. 데이터베이스 연결과 Java 준비 상태를 확인해 주세요.')
            return readiness
        driver = url.lower()
        if driver.startswith('jdbc:') or ':jdbc:' in driver or 'hsqldb' in driver:
            readiness['javaRequired'] = True
        elif driver.startswith(('sdbc:embedded:firebird', 'sdbc:firebird:', 'sdbc:odbc:',
                                'sdbc:postgresql:', 'sdbc:mysql:mysqlc:')):
            readiness['javaRequired'] = False
    except Exception:
        return readiness
    try:
        readiness['connectionVerified'] = bool(document.getCurrentController().isConnected())
        readiness['state'] = 'connected' if readiness['connectionVerified'] else 'not_connected'
    except Exception:
        # A missing controller does not erase the independently observed URL.
        pass
    if context is not None:
        try:
            manager = context.ServiceManager.createInstanceWithContext('com.sun.star.sdbc.DriverManager', context)
            readiness['driverAvailable'] = manager.getDriverByURL(url) is not None
        except Exception:
            # Probe failure is unknown; an observed null driver is False.
            pass
        if readiness['javaRequired']:
            try:
                vm = context.ServiceManager.createInstanceWithContext('com.sun.star.java.JavaVirtualMachine', context)
            except Exception:
                vm = None
            if vm is not None:
                # Keep partial facts if one of these independent getters fails.
                for field, method in (('javaEnabled', 'isVMEnabled'), ('javaStarted', 'isVMStarted')):
                    try:
                        value = getattr(vm, method)()
                        if type(value) is bool:
                            readiness[field] = value
                    except Exception:
                        pass
                if readiness['javaStarted'] is True:
                    readiness['javaAvailable'] = True
    connection = ('현재 데이터베이스 연결을 확인했습니다. 추가 기능은 별도 확인이 필요합니다.'
                  if readiness['connectionVerified'] else '데이터베이스 연결은 확인되지 않았습니다.')
    if readiness['javaRequired'] and readiness['javaEnabled'] is False:
        # HSQLDB/JDBC acceptsURL itself returns False when Java is disabled.
        readiness['message'] = 'Java 사용이 꺼져 있습니다. 이 데이터 원본에 필요한 Java 설정을 확인해 주세요. ' + connection
    elif readiness['driverAvailable'] is False:
        readiness['message'] = '이 데이터 원본에 맞는 Base 드라이버를 찾지 못했습니다. 드라이버 구성을 확인해 주세요. ' + connection
    elif readiness['driverAvailable'] is None:
        readiness['message'] = 'Base 드라이버 준비 상태를 확인하지 못했습니다. ' + connection
    elif readiness['javaRequired'] and readiness['javaAvailable'] is None:
        readiness['message'] = 'Base 드라이버는 확인했지만 사용 가능한 JRE는 검증되지 않았습니다. ' + connection
    elif readiness['javaRequired']:
        readiness['message'] = 'Base 드라이버와 실행 중인 Java VM을 확인했습니다. ' + connection
    elif readiness['javaRequired'] is False:
        readiness['message'] = 'Base 네이티브 드라이버를 확인했습니다. ' + connection
    else:
        readiness['message'] = 'Base 드라이버를 확인했습니다. Java 필요 여부는 확인되지 않았습니다. ' + connection
    return readiness


class UnoBackend:
    def __init__(self, runtime, process_factory=None, window_api=None, uno_loader=None, connector=None):
        self.runtime = Path(runtime)
        self.process_factory = process_factory
        self.window_api = window_api
        self.uno_loader = uno_loader or (lambda: importlib.import_module('uno'))
        self.connector = connector or connect_uno
        self.process = self.profile = self.document = self.desktop = self.frame = self.peer = None
        self.context = None
        self.uno = None
        self.interceptor = None
        self.pipe = 'OpenGeul_' + uuid.uuid4().hex
        self.command_handler = lambda command, target_module=None: None
        self.module_factory = None

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

    def _new_base_url(self, service, module, interaction):
        # A noninteractive Base factory leaves URL="jdbc:" and selects Tables,
        # which can attempt that invalid connection. Initialize a local Firebird
        # document first, then use the existing-file loader in our named frame.
        owned = Path(self.profile.name) / '새 데이터베이스.odb'
        if owned.exists() or owned.is_symlink():
            raise WorkerError('new_database_failed', '새 데이터베이스의 임시 경로가 이미 존재합니다.')
        generated = None
        try:
            generated = service('com.sun.star.sdb.OfficeDatabaseDocument')
            generated.initNew()
            generated.DataSource.setPropertyValue('URL', 'sdbc:embedded:firebird')
            props = tuple(self._property(name, value) for name, value in (
                ('FilterName', module['filters']['odb']), ('Overwrite', False),
                ('MacroExecutionMode', 0), ('UpdateDocMode', 0), ('InteractionHandler', interaction)))
            generated.storeAsURL(owned.as_uri(), props)
            if owned.is_symlink() or not owned.is_file() or not owned.stat().st_size or generated.isModified():
                raise WorkerError('new_database_failed', '새 데이터베이스의 초기 저장을 확인하지 못했습니다.')
            generated.close(False)
            return owned.as_uri()
        except Exception as exc:
            # This model was generated here and has never been shown to the user.
            # Never clear/dispose the subsequently loaded user document's state.
            if generated is not None:
                try:
                    generated.dispose()
                except Exception:
                    pass
            raise WorkerError('new_database_failed', '새 Firebird 데이터베이스를 만들지 못했습니다.') from exc

    def attach(self, hwnd, module, width, height, path):
        self.module_factory = module['factory']
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
        self.context = context
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
        if path is None and module['factory'] == 'private:factory/sdatabase':
            url = self._new_base_url(service, module, interaction)
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
        result = {'modified': bool(self.document.isModified()), 'title': str(self.document.getTitle())}
        if self.module_factory == 'private:factory/sdatabase':
            result['readiness'] = base_readiness(self.document, self.context)
        return result

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
        self.context = self.document = self.desktop = self.frame = self.peer = self.interceptor = None
        if self.profile is not None:
            try:
                self.profile.cleanup()
                self.profile = None
            except OSError:
                pass
