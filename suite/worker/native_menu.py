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


def _require(condition):
    if not condition:
        raise ValueError('Required owned native menu interface is unavailable')


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


def _descriptors(container, maximum):
    count = container.getCount()
    _require(type(count) is int and 0 < count <= maximum)
    result = []
    for index in range(count):
        row = container.getByIndex(index)
        _require(isinstance(row, (tuple, list)) and 0 < len(row) <= 32)
        props = {}
        for prop in row:
            _require(type(prop.Name) is str and prop.Name not in props)
            props[prop.Name] = prop.Value
        result.append(props)
    return result


class NativeMenuSurface:
    def __init__(self, backend):
        self.frame, self.peer = backend.frame, backend.peer
        self.document, self.interceptor = backend.document, backend.interceptor
        self.factory = backend.module_factory
        self.controller = self.manager = None
        self.attempted = self.shown = False
        self.failure = None

    def _owner(self, backend, *, bind=False):
        _require(all(value is not None for value in (self.frame, self.peer, self.document, self.interceptor)))
        _require(self.factory in OPEN_COMMANDS and isinstance(self.interceptor, DispatchRouter))
        _require(all(getattr(backend, key, None) is value for key, value in (
            ('frame', self.frame), ('peer', self.peer), ('document', self.document),
            ('interceptor', self.interceptor))))
        _require(backend.module_factory == self.factory)
        controller = self.frame.getController()
        _require(controller is not None and self.frame.getContainerWindow() == self.peer
                 and self.document.getCurrentController() == controller
                 and controller.getFrame() == self.frame and controller.getModel() == self.document)
        if bind:
            self.controller = controller
        _require(self.controller is not None and controller == self.controller)

    def _element(self):
        _require(self.frame.getPropertyValue('LayoutManager') == self.manager)
        element = self.manager.getElement(RESOURCE)
        _require(element is not None and element.Frame == self.frame and element.ResourceURL == RESOURCE
                 and type(element.Type) is int and element.Type == 1)
        return element

    def _file_popup(self, element):
        menu = element.getRealInterface()
        _require(menu is not None and menu.isPopupMenu() is False)
        file_items = [item for item, command in _items(menu, MAX_BAR_ITEMS) if command == FILE_MENU]
        _require(len(file_items) == 1 and menu.isItemEnabled(file_items[0]) is True)
        popup = menu.getPopupMenu(file_items[0])
        _require(popup is not None and popup.isPopupMenu() is True)
        return popup

    def _core_commands(self):
        return ('.uno:AddDirect', OPEN_COMMANDS[self.factory], '.uno:Save', '.uno:SaveAs',
                '.uno:CloseDoc', '.uno:Quit')

    def _product_items(self, backend, element):
        # XUIElementSettings creates writable copies of the original descriptors.
        # Persistent=False makes setSettings update this frame's MenuBarManager,
        # without writing configuration or mutating the toolkit data wrapper.
        settings = element.getSettings(True)
        files = [row for row in _descriptors(settings, MAX_BAR_ITEMS) if row.get('CommandURL') == FILE_MENU]
        _require(len(files) == 1)
        popup = files[0].get('ItemDescriptorContainer')
        original = _descriptors(popup, MAX_FILE_ITEMS - 2)
        _require(not any(row.get('CommandURL') in (HOME, NEW_HWP) for row in original))
        for command, label in ((HOME, 'OpenGeul 시작 화면'), (NEW_HWP, '새 HWP 문서')):
            values = []
            for name, value in (('CommandURL', command), ('Label', label), ('Type', 0)):
                prop = backend.uno.createUnoStruct('com.sun.star.beans.PropertyValue')
                prop.Name, prop.Value = name, value
                values.append(prop)
            popup.insertByIndex(0, backend.uno.Any('[]com.sun.star.beans.PropertyValue', tuple(values)))
        element.setPropertyValue('Persistent', False)
        _require(element.getPropertyValue('Persistent') is False)
        element.setSettings(settings)

    def _fail(self, cause):
        if self.failure is None:
            self.failure = WorkerError(ERROR_CODE, 'Office 문서 메뉴에 연결할 수 없습니다. 문서를 안전하게 닫아 주세요.')
        raise self.failure from cause

    def prepare(self, backend):
        if self.failure is not None:
            raise self.failure
        if self.attempted:
            return self.ready(backend)
        self.attempted = True
        try:
            self._owner(backend, bind=True)
            self.manager = self.frame.getPropertyValue('LayoutManager')
            _require(self.manager is not None and self.manager.showElement(RESOURCE) is True)
            # Pinned LayoutManager returns True only after SetMenuBar on the
            # actual SystemWindow. Visibility alone can be a logical fallback.
            self.shown = True
            element = self._element()
            original = {command for _, command in _items(self._file_popup(element), MAX_FILE_ITEMS)}
            _require(set(self._core_commands()) <= original)
            self._product_items(backend, element)
        except Exception as exc:
            self._fail(exc)
        return self.ready(backend)

    def ready(self, backend):
        if self.failure is not None:
            raise self.failure
        try:
            _require(self.shown)
            self._owner(backend)
            _require(self.manager.isElementVisible(RESOURCE) is True)
            element = self._element()
            _require(element.getPropertyValue('Persistent') is False)
            commands = {command for _, command in _items(self._file_popup(element), MAX_FILE_ITEMS)}
            required = (NEW_HWP, HOME, *self._core_commands())
            _require(set(required) <= commands)
            for command in required:
                url = backend.uno.createUnoStruct('com.sun.star.util.URL')
                protocol, path = command.split(':', 1)
                url.Complete, url.Protocol, url.Path = command, protocol + ':', path
                _require(self.interceptor.queryDispatch(url, '_self', 0) is self.interceptor)
                dispatch = self.frame.queryDispatch(url, '_self', 0)
                # PyUNO_cmp supports equality with the original exported Python
                # adapter; Python object identity alone is not a UNO identity check.
                _require(dispatch is not None and dispatch == self.interceptor
                         and callable(getattr(dispatch, 'dispatch', None)))
            return True
        except Exception as exc:
            self._fail(exc)
