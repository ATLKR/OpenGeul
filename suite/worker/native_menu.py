"""Bind the retained frame's required native menu; later checks are passive."""
from dispatch import DispatchRouter
from session import WorkerError

RESOURCE = 'private:resource/menubar/menubar'
FILE_MENU = '.uno:PickList'
HOME = '.uno:StartModule'
NEW_HWP = 'vnd.opengeul.office:new-hwp'
ERROR_CODE = 'native_menu_unavailable'
OPEN_COMMANDS = {
    'private:factory/swriter': '.uno:OpenFromWriter',
    'private:factory/scalc': '.uno:OpenFromCalc',
    'private:factory/simpress': '.uno:Open',
    'private:factory/sdraw': '.uno:Open',
    'private:factory/smath': '.uno:Open',
    'private:factory/sdatabase': '.uno:Open',
}
MAX_BAR_ITEMS, MAX_FILE_ITEMS = 64, 256
# Closed diagnostic IDs: 00 entry, 01 fixed anchors, 02 controller/model,
# 03 show, 04 initial visibility, 05 resource metadata, 06 XMenuBar property,
# 07 menubar shape, 08 File popup, 09 File commands, 10 owned interceptor,
# 11 frame dispatch, 12 owner snapshot, 13 element snapshot, 14 epoch bound.
# Only these fixed phase strings reach the existing optional recorder.
CHECK_PHASES = tuple('native-menu-check-' + format(code, '02d') for code in range(15))


def _require(condition):
    if not condition:
        raise ValueError('Required owned native menu interface is unavailable')


class _MenuUnavailable(Exception):
    """A captured menu object no longer supplies its native interface."""


def _items(menu, maximum):
    count = menu.getItemCount()
    _require(type(count) is int and 0 < count <= maximum)
    result = []
    for index in range(count):
        item = menu.getItemId(index)
        _require(type(item) is int and 0 <= item <= 32767)
        if item == 0:  # A separator has no command or popup identity.
            continue
        command = menu.getCommand(item)
        _require(type(command) is str)
        result.append((item, command))
    return result


class NativeMenuSurface:
    def __init__(self, backend):
        self.frame, self.peer = backend.frame, backend.peer
        self.document, self.interceptor = backend.document, backend.interceptor
        self.factory = backend.module_factory
        self.manager = None
        self.attempted = self.shown = False
        self.failure = None
        self.check = 0

    def _anchors(self, backend):
        self.check = 1
        _require(all(value is not None for value in (self.frame, self.peer, self.document, self.interceptor)))
        _require(self.factory in OPEN_COMMANDS and isinstance(self.interceptor, DispatchRouter))
        _require(all(getattr(backend, key, None) is value for key, value in (
            ('frame', self.frame), ('peer', self.peer), ('document', self.document),
            ('interceptor', self.interceptor))))
        _require(backend.module_factory == self.factory)
        _require(self.frame.getContainerWindow() == self.peer)

    def _owner(self, backend):
        self._anchors(backend)
        self.check = 2
        controller = self.frame.getController()
        _require(controller is not None)
        current = self.document.getCurrentController()
        owner_frame, owner_model = controller.getFrame(), controller.getModel()
        # Disposed old views may return null. Foreign non-null owners are fatal
        # before any epoch comparison and cannot authorize a second observation.
        _require((owner_frame is None or owner_frame == self.frame)
                 and (owner_model is None or owner_model == self.document))
        if current != controller:
            _require(current is not None and current.getFrame() == self.frame
                     and current.getModel() == self.document)
        self._anchors(backend)
        self.check = 2
        return controller, (current == controller and owner_frame == self.frame
                            and owner_model == self.document)

    def _disposed(self, backend, error):
        try:
            return isinstance(error, backend.uno.getClass('com.sun.star.lang.DisposedException'))
        except Exception:
            return False

    def _element(self):
        self.check = 5
        _require(self.frame.getPropertyValue('LayoutManager') == self.manager)
        element = self.manager.getElement(RESOURCE)
        if element is None:
            raise _MenuUnavailable('Native menu element is unavailable')
        # XUIElement metadata are IDL attributes. Use the public property-set
        # getters; their raw Any values do not depend on descriptor type names.
        _require(element.getPropertyValue('Frame') == self.frame
                 and element.getPropertyValue('ResourceURL') == RESOURCE)
        element_type = element.getPropertyValue('Type')
        _require(type(element_type) is int and element_type == 1)
        return element

    def _file_popup(self, element):
        self.check = 6
        # getRealInterface() is MenuBarManager (XSystemDependentMenuPeer),
        # not XMenu. The wrapper exposes its actual VCL XMenuBar read-only.
        menu = element.getPropertyValue('XMenuBar')
        if menu is None:
            raise _MenuUnavailable('Native menu interface is unavailable')
        self.check = 7
        _require(menu.isPopupMenu() is False)
        file_items = [item for item, command in _items(menu, MAX_BAR_ITEMS) if command == FILE_MENU]
        _require(len(file_items) == 1 and menu.isItemEnabled(file_items[0]) is True)
        self.check = 8
        popup = menu.getPopupMenu(file_items[0])
        if popup is None:
            raise _MenuUnavailable('Native File popup is unavailable')
        _require(popup.isPopupMenu() is True)
        return popup

    def _core_commands(self):
        return ('.uno:AddDirect', OPEN_COMMANDS[self.factory], '.uno:Save', '.uno:SaveAs',
                '.uno:CloseDoc', '.uno:Quit')

    def _fail(self, cause, backend):
        if self.failure is None:
            self.failure = WorkerError(ERROR_CODE, 'Office 문서 메뉴에 연결할 수 없습니다. 문서를 안전하게 닫아 주세요.')
            try:
                diagnose = getattr(backend, '_diagnose', None)
                if callable(diagnose):
                    diagnose(CHECK_PHASES[self.check])
            except Exception:
                # Optional evidence must not replace the primary owned error.
                pass
        raise self.failure from cause

    def prepare(self, backend):
        if self.failure is not None:
            raise self.failure
        if self.attempted:
            return self.ready(backend)
        self.attempted = True
        try:
            _require(self._owner(backend)[1])
            self.check = 3
            self.manager = self.frame.getPropertyValue('LayoutManager')
            _require(self.manager is not None and self.manager.showElement(RESOURCE) is True)
            # Pinned LayoutManager returns True only after SetMenuBar on the
            # actual SystemWindow. Visibility alone can be a logical fallback.
            self.shown = True
            self.check = 4
            _require(self.manager.isElementVisible(RESOURCE) is True)
        except Exception as exc:
            self._fail(exc, backend)
        return self.ready(backend)

    def ready(self, backend):
        if self.failure is not None:
            raise self.failure
        try:
            self.check = 0
            _require(self.shown)
            expected = None
            # One completed native view switch can cross separate UNO getters.
            # Reobserve the whole owner/menu/dispatch snapshot once, never nest
            # owner retries inside menu retries or repeat UI/input operations.
            for attempt in range(2):
                controller, connected = self._owner(backend)
                if expected is not None:
                    self.check = 12
                    _require(controller == expected[0])
                element = None
                unavailable = None
                unavailable_check = None
                if not connected:
                    unavailable = _MenuUnavailable('Old controller connection is unavailable')
                    unavailable_check = 2
                else:
                    try:
                        element = self._element()
                    except _MenuUnavailable as exc:
                        unavailable = exc
                        unavailable_check = self.check
                    if unavailable is None:
                        if expected is not None:
                            self.check = 13
                            _require(element == expected[1])
                        try:
                            popup = self._file_popup(element)
                            self.check = 9
                            commands = [command for _, command in _items(
                                popup, MAX_FILE_ITEMS)]
                        except Exception as exc:
                            # Only the captured menu's null/disposed state may
                            # cross an epoch. Fixed anchors and actual dispatch
                            # failures never enter this recovery path.
                            if not isinstance(exc, _MenuUnavailable) and not self._disposed(backend, exc):
                                raise
                            unavailable = exc
                            unavailable_check = self.check
                        if unavailable is None:
                            self.check = 9
                            required = (NEW_HWP, HOME, *self._core_commands())
                            _require(all(commands.count(command) == 1 for command in required))
                            for command in required:
                                self.check = 10
                                url = backend.uno.createUnoStruct('com.sun.star.util.URL')
                                protocol, path = command.split(':', 1)
                                url.Complete, url.Protocol, url.Path = command, protocol + ':', path
                                _require(self.interceptor.queryDispatch(url, '_self', 0) is self.interceptor)
                                self.check = 11
                                dispatch = self.frame.queryDispatch(url, '_self', 0)
                                _require(dispatch is not None and dispatch == self.interceptor
                                         and callable(getattr(dispatch, 'dispatch', None)))
                if unavailable is not None and attempt != 0:
                    self.check = unavailable_check
                    raise unavailable
                # A fresh candidate must already have valid fixed owners and
                # resource metadata. The next whole read must keep this exact
                # candidate through its end; a third epoch is always fatal.
                after, after_connected = self._owner(backend)
                self.check = 12
                _require(after_connected)
                current_element = self._element()
                tail, tail_connected = self._owner(backend)
                self.check = 12
                _require(tail_connected and tail == after)
                if controller == after and element == current_element:
                    if unavailable is not None:
                        self.check = unavailable_check
                        raise unavailable
                    return True
                self.check = 14
                _require(attempt == 0 and (connected or controller != after))
                expected = after, current_element
            _require(False)
        except Exception as exc:
            self._fail(exc, backend)
