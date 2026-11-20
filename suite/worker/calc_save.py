"""One owned native Calc Save transaction, including its active-cell handling.

This follows ordinary Calc Save. Its result is not a universal completion signal
for asynchronous validation or formula-correction dialogs.
"""
from pathlib import Path
from urllib.parse import urlsplit

from dispatch import make_interaction_handler
from session import WorkerError, local_path
from save_diagnostics import trace_calc_save

CALC_SERVICE = 'com.sun.star.sheet.SpreadsheetDocument'
CONFIG_PATH = '/org.openoffice.Office.Common/Save/Document'
SAVE_POLICY = {'WarnAlienFormat': False, 'AlwaysSaveAs': False}


def _failed():
    return WorkerError('save_failed', 'Calc 저장 결과와 문서 소유권을 확인하지 못했습니다. 문서를 열어 둡니다.')


class CalcSaveTransaction:
    def __init__(self, backend, filters, path, parent_hwnd, child_hwnd):
        self.backend = backend
        self.document, self.frame, self.peer = backend.document, backend.frame, backend.peer
        self.controller = self.document.getCurrentController()
        self.filters, self.path = dict(filters), path
        self.parent_hwnd, self.child_hwnd = parent_hwnd, child_hwnd
        self.saving = False
        # This backend has its own process and new PrivateProfile. The Suite
        # picker already selected the destination/format; native format warnings
        # must not redirect ordinary Save into another Save As picker.
        provider = self._service('com.sun.star.configuration.ConfigurationProvider')
        config = provider.createInstanceWithArguments(
            'com.sun.star.configuration.ConfigurationUpdateAccess',
            (backend._property('nodepath', CONFIG_PATH),))
        for name, value in SAVE_POLICY.items():
            config.setPropertyValue(name, value)
        config.commitChanges()
        self._policy()
        self._owned()

    def _service(self, name):
        context = self.backend.context
        return context.ServiceManager.createInstanceWithContext(name, context)

    def _policy(self):
        provider = self._service('com.sun.star.configuration.ConfigurationProvider')
        config = provider.createInstanceWithArguments(
            'com.sun.star.configuration.ConfigurationAccess',
            (self.backend._property('nodepath', CONFIG_PATH),))
        for name in SAVE_POLICY:
            value = config.getPropertyValue(name)
            if type(value) is not bool or value is not False:
                raise _failed()

    def _owned(self):
        b = self.backend
        if (b.document != self.document or b.frame != self.frame or b.peer != self.peer
                or self.controller is None or b.process is None or b.process.poll() is not None
                or not self.document.supportsService(CALC_SERVICE)
                or self.document.getCurrentController() != self.controller
                or self.controller.getModel() != self.document
                or self.controller.getFrame() != self.frame
                or self.frame.getController() != self.controller
                or self.frame.getContainerWindow() != self.peer
                or self.frame.getCreator() != b.desktop
                or int(self.peer.getWindowHandle((), 1)) != self.child_hwnd):
            raise _failed()
        frames = b.desktop.getFrames()
        if frames.getCount() != 1 or frames.getByIndex(0) != self.frame:
            raise _failed()
        b.window_api.validate_child(self.child_hwnd, self.parent_hwnd)

    def _same_location(self, path):
        url = self.document.getURL()
        parsed = urlsplit(url)
        if (parsed.scheme != 'file' or parsed.netloc or parsed.query or parsed.fragment
                or not parsed.path or '\x00' in url):
            raise _failed()
        # Convert with UNO rather than compare URI spelling: Windows drive case,
        # Unicode and percent-escaped spaces may differ in the model URL.
        actual = local_path(self.backend.uno.fileUrlToSystemPath(url))
        if actual != path:
            raise _failed()

    def _current_filter(self, expected):
        filters = [p.Value for p in self.document.getArgs() if p.Name == 'FilterName']
        if filters != [expected]:
            raise _failed()

    def _export_filter(self, filter_name):
        properties = self._service('com.sun.star.document.FilterFactory').getByName(filter_name)
        flags = [p.Value for p in properties if p.Name == 'Flags']
        if len(flags) != 1 or type(flags[0]) is not int or not flags[0] & 2:  # FilterFlags.EXPORT
            raise _failed()

    def save(self, path, filter_name):
        if self.saving:
            raise _failed()
        self.saving = True
        try:
            self._owned()
            self._policy()
            if path is None:
                if self.path is None or filter_name is not None:
                    raise _failed()
                if not self.document.hasLocation() or self.document.isReadonly():
                    raise _failed()
                self._same_location(self.path)
                expected = self.filters.get(self.path.suffix.lower().lstrip('.'))
                if not expected:
                    raise _failed()
                self._current_filter(expected)
                self._export_filter(expected)
                destination, command = self.path, '.uno:Save'
                args = [('DontTerminateEdit', False)]
            else:
                # DocumentSession also validates this boundary. Do not accept an
                # unowned native picker or an arbitrary filter at dispatch time.
                if not isinstance(path, Path) or local_path(str(path)) != path:
                    raise _failed()
                expected = self.filters.get(path.suffix.lower().lstrip('.'))
                if not expected or filter_name != expected:
                    raise _failed()
                self._export_filter(expected)
                destination, command = path, '.uno:SaveAs'
                args = [('URL', path.as_uri()), ('FilterName', expected), ('Overwrite', True)]
            self.frame.activate()
            self._owned()
            if not self.frame.isActive():
                raise _failed()
            url = self.backend.uno.createUnoStruct('com.sun.star.util.URL')
            url.Complete = command
            url.Protocol, url.Path = '.uno:', command[len('.uno:'):]
            # Controller .uno resolution returns its retained view's native slot
            # (sfxbasecontroller.cxx:716-747), bypassing frame interception.
            dispatch = self.controller.queryDispatch(url, '_self', 0)
            if dispatch is None or not callable(getattr(dispatch, 'dispatchWithNotification', None)):
                raise _failed()
            args.extend((('InteractionHandler', make_interaction_handler()), ('OnMainThread', True)))
            helper = self._service('com.sun.star.frame.DispatchHelper')
            # DispatchHelper marshals the complete operation to VCL's main
            # thread and returns its notifying-dispatch result. Direct notifying
            # dispatch ignores OnMainThread in this pinned engine.
            trace_calc_save('begin', command)
            try:
                result = helper.executeDispatch(self.controller, command, '_self', 0,
                    tuple(self.backend._property(name, value) for name, value in args))
            except Exception as exc:
                trace_calc_save('error', command, exception_type=type(exc).__name__)
                raise
            self._owned()
            self._policy()
            if not self.frame.isActive():
                raise _failed()
            if (result is None or type(getattr(result, 'State', None)) is not int
                    or result.State != 1 or type(getattr(result, 'Result', None)) is not bool
                    or result.Result is not True):
                raise _failed()
            self._same_location(destination)
            self._current_filter(expected)
            if self.document.isModified():
                raise _failed()
            self.path = destination
            trace_calc_save('end', command, state=result.State, result=result.Result)
        finally:
            self.saving = False
