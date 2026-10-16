"""Validated document-session state, independent of the UNO transport."""
from pathlib import Path
import os

FACTORIES = {'writer': 'private:factory/swriter', 'calc': 'private:factory/scalc',
             'impress': 'private:factory/simpress', 'draw': 'private:factory/sdraw',
             'math': 'private:factory/smath', 'base': 'private:factory/sdatabase'}


class WorkerError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def local_path(value, *, must_exist=False):
    if not isinstance(value, str) or not value or '\x00' in value:
        raise WorkerError('invalid_path', '로컬 파일의 절대 경로가 필요합니다.')
    if value.startswith(('\\\\', '//')) or '://' in value:
        raise WorkerError('invalid_path', '네트워크 경로와 URL은 열 수 없습니다.')
    path = Path(value)
    if not path.is_absolute():
        raise WorkerError('invalid_path', '로컬 파일의 절대 경로가 필요합니다.')
    try:
        path = path.resolve(strict=must_exist)
        if os.name == 'nt':
            import ctypes
            # A mapped network drive is also remote even if it has a drive letter.
            get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
            get_drive_type.argtypes, get_drive_type.restype = [ctypes.c_wchar_p], ctypes.c_uint
            if get_drive_type(path.anchor) not in (2, 3, 5, 6):
                raise WorkerError('invalid_path', '로컬 디스크의 파일을 선택해 주세요.')
        if (must_exist and not path.is_file()) or (not must_exist and not path.parent.is_dir()):
            raise WorkerError('invalid_path', '파일 또는 저장 폴더를 찾을 수 없습니다.')
        if path.exists() and not path.is_file():
            raise WorkerError('invalid_path', '파일 경로를 선택해 주세요.')
    except (OSError, ValueError) as exc:
        raise WorkerError('invalid_path', '파일 경로에 접근할 수 없습니다.') from exc
    return path


def positive_integer(value, label, maximum):
    if type(value) is not int or not 0 < value <= maximum:
        raise WorkerError('invalid_request', label + ' 값이 올바르지 않습니다.')
    return value


def dimensions(args):
    return (positive_integer(args.get('width'), 'width', 32768),
            positive_integer(args.get('height'), 'height', 32768))


class DocumentSession:
    def __init__(self, runtime, modules, backend_factory=None):
        self.runtime = Path(runtime)
        self.modules = modules
        self.backend_factory = backend_factory
        self.backend = None
        self.state = 'idle'
        self.module = None
        self.path = None
        self.handles = {}
        self.event_sink = lambda event: None

    def dispatch(self, command, args):
        if not isinstance(args, dict):
            raise WorkerError('invalid_request', 'args는 JSON 객체여야 합니다.')
        handlers = {'attach': self._attach, 'resize': self._resize, 'status': self._status,
                    'save': self._save, 'close': self._close, 'shutdown': self._shutdown}
        if command not in handlers:
            raise WorkerError('unknown_command', '지원하지 않는 작업자 명령입니다.')
        if self.state == 'stopped':
            raise WorkerError('invalid_state', '작업자가 이미 종료되었습니다.')
        return handlers[command](args)

    def _require_attached(self):
        if self.state != 'attached':
            raise WorkerError('invalid_state', '열린 문서가 없습니다.')

    def _attach(self, args):
        if self.state not in ('idle', 'closed'):
            raise WorkerError('invalid_state', '문서가 이미 열려 있습니다.')
        module_id = args.get('module')
        if not isinstance(module_id, str) or module_id not in FACTORIES or module_id not in self.modules:
            raise WorkerError('unsupported_module', '지원하지 않는 Office 모듈입니다.')
        module = self.modules[module_id]
        if module.get('factory') != FACTORIES[module_id]:
            raise WorkerError('invalid_manifest', 'Office 모듈 설정이 올바르지 않습니다.')
        hwnd = positive_integer(args.get('parentHwnd'), 'parentHwnd', (1 << 63) - 1)
        width, height = dimensions(args)
        path = local_path(args['path'], must_exist=True) if args.get('path') is not None else None
        if path and path.suffix.lower().lstrip('.') not in module['extensions']:
            raise WorkerError('unsupported_format', '선택한 모듈에서 지원하지 않는 파일 형식입니다.')
        if self.backend_factory is None:
            from native import UnoBackend
            factory = UnoBackend
        else:
            factory = self.backend_factory
        backend = factory(self.runtime)
        if hasattr(backend, 'set_command_handler'):
            def forward_command(command, target_module=None):
                selected_module = module_id if target_module is None else target_module
                if (selected_module not in self.modules or selected_module not in FACTORIES
                        or self.modules[selected_module].get('factory') != FACTORIES[selected_module]):
                    return
                self.event_sink({'event': 'command', 'command': command, 'module': selected_module})
            backend.set_command_handler(forward_command)
        try:
            handles = backend.attach(hwnd, module, width, height, path)
            if not handles.get('childHwnd'):
                raise WorkerError('attach_failed', '내장 편집기 창을 확인할 수 없습니다.')
        except Exception as exc:
            backend.cleanup()
            if isinstance(exc, WorkerError):
                raise
            raise WorkerError('attach_failed', 'Office 내장 편집기를 시작하지 못했습니다.') from exc
        self.backend, self.module, self.path = backend, module_id, path
        self.handles, self.state = handles, 'attached'
        return self._status({})

    def _status(self, args):
        self._require_attached()
        state = self.backend.status()
        return dict(state, module=self.module, path=str(self.path) if self.path else None, **self.handles)

    def _resize(self, args):
        self._require_attached()
        self.backend.resize(*dimensions(args))
        return {'resized': True}

    def _save(self, args):
        self._require_attached()
        path = local_path(args['path']) if args.get('path') is not None else None
        filter_name = args.get('filter')
        if path is None:
            if not self.path:
                raise WorkerError('invalid_state', '새 문서의 저장 경로를 선택해 주세요.')
            if filter_name is not None:
                raise WorkerError('invalid_request', '다른 형식은 새 저장 경로와 함께 선택해 주세요.')
        else:
            expected = self.modules[self.module]['filters'].get(path.suffix.lower().lstrip('.'))
            if not expected or (filter_name is not None and filter_name != expected):
                raise WorkerError('unsupported_format', '저장 확장자와 필터가 지원되는 형식과 일치해야 합니다.')
            filter_name = expected
        try:
            self.backend.save(path, filter_name)
        except Exception as exc:
            raise WorkerError('save_failed', '문서를 저장하지 못했습니다. 문서를 열어 둡니다.') from exc
        if path is not None:
            self.path = path
        return self._status({})

    def _close(self, args):
        self._require_attached()
        discard = args.get('discard', False)
        if type(discard) is not bool:
            raise WorkerError('invalid_request', 'discard는 true 또는 false여야 합니다.')
        if not discard and self.backend.status()['modified']:
            return {'closed': False, 'closeCancelled': True}
        try:
            self.backend.close(discard)
        except Exception as exc:
            raise WorkerError('close_failed', '문서 닫기가 취소되었습니다. 문서를 열어 둡니다.') from exc
        self.backend.cleanup()
        self.backend, self.state = None, 'closed'
        return {'closed': True, 'closeCancelled': False}

    def _shutdown(self, args):
        discard = args.get('discard', False)
        if type(discard) is not bool:
            raise WorkerError('invalid_request', 'discard는 true 또는 false여야 합니다.')
        if self.state == 'attached':
            result = self._close(args)
            if result['closeCancelled']:
                return result
        self.state = 'stopped'
        return {'closed': True, 'closeCancelled': False, 'shutdown': True}
