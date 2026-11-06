"""Route native document-management actions back to the owning Suite form."""
from session import FACTORIES
from save_diagnostics import trace_native_dispatch

FACTORY_MODULES = {factory: module for module, factory in FACTORIES.items()}

COMMANDS = {'.uno:Open': 'open', '.uno:OpenUrl': 'open',
            '.uno:OpenFromWriter': 'open', '.uno:OpenFromCalc': 'open',
            '.uno:AddDirect': 'new', '.uno:NewDoc': 'new', '.uno:Save': 'save', '.uno:SaveAs': 'saveAs',
            '.uno:CloseDoc': 'close', '.uno:CloseWin': 'close', '.uno:CloseFrame': 'close',
            '.uno:Quit': 'exit', '.uno:Exit': 'exit', '.uno:StartModule': 'home'}
DISABLED_COMMANDS = ('.uno:SaveAll', '.uno:SaveACopy', '.uno:SaveAsTemplate',
                     '.uno:SaveAsRemote', '.uno:OpenRemote', '.uno:NewWindow')
PRODUCT_PROTOCOL = 'vnd.opengeul.office:'
HWP_NEW_URL = PRODUCT_PROTOCOL + 'new-hwp'


class DispatchRouter:
    def __init__(self, on_command):
        self.on_command = on_command
        self.slave = None
        self.master = None
        self.save_receipt_sequence = 0

    def queryDispatch(self, url, target, flags):
        name = url.Complete.split('?', 1)[0]
        if name in COMMANDS or name in DISABLED_COMMANDS or name.startswith(('private:factory/', 'file:', PRODUCT_PROTOCOL)):
            return self
        if self.slave is not None and self.slave is not self:
            return self.slave.queryDispatch(url, target, flags)
        return None

    def queryDispatches(self, descriptors):
        return tuple(self.queryDispatch(d.FeatureURL, d.FrameName, d.SearchFlags) for d in descriptors)

    def dispatch(self, url, arguments):
        name = url.Complete.split('?', 1)[0]
        if name.startswith(PRODUCT_PROTOCOL):
            if url.Complete == HWP_NEW_URL:
                self.on_command('new', 'hwp')
            return
        if name.startswith('private:factory/'):
            target_module = FACTORY_MODULES.get(url.Complete)
            if target_module is not None:
                self.on_command('new', target_module)
            # Unknown factories and query arguments never reach a native launcher.
            return
        command = 'open' if name.startswith('file:') else COMMANDS.get(name)
        if command:
            if command in ('save', 'saveAs'):
                self.save_receipt_sequence += 1
                trace_native_dispatch(self.save_receipt_sequence, command, name)
            self.on_command(command)

    def addStatusListener(self, listener, url):
        # The Suite owns supported actions and explicitly declines unsupported semantics.
        try:
            import uno
            event = uno.createUnoStruct('com.sun.star.frame.FeatureStateEvent')
            name = url.Complete.split('?', 1)[0]
            enabled = name not in DISABLED_COMMANDS
            if name.startswith(PRODUCT_PROTOCOL):
                enabled = url.Complete == HWP_NEW_URL
            event.Source, event.FeatureURL, event.IsEnabled = self, url, enabled
            listener.statusChanged(event)
        except Exception:
            pass

    def removeStatusListener(self, listener, url):
        pass

    def getSlaveDispatchProvider(self):
        return self.slave

    def setSlaveDispatchProvider(self, provider):
        self.slave = provider

    def getMasterDispatchProvider(self):
        return self.master

    def setMasterDispatchProvider(self, provider):
        self.master = provider

    def getInterceptedURLs(self):
        return tuple(COMMANDS) + DISABLED_COMMANDS + (HWP_NEW_URL, PRODUCT_PROTOCOL + '*', 'private:factory/*', 'file:*')


def make_interceptor(on_command):
    # PyUNO imports occur only in the Windows runtime interpreter after attachment.
    import unohelper
    from com.sun.star.frame import XDispatch, XDispatchProviderInterceptor, XInterceptorInfo

    class UnoInterceptor(unohelper.Base, DispatchRouter, XDispatchProviderInterceptor, XInterceptorInfo, XDispatch):
        def __init__(self):
            DispatchRouter.__init__(self, on_command)

    return UnoInterceptor()


def make_interaction_handler():
    import uno
    import unohelper
    from com.sun.star.task import XInteractionHandler

    class AbortInteraction(unohelper.Base, XInteractionHandler):
        def handle(self, request):
            abort_type = uno.getTypeByName('com.sun.star.task.XInteractionAbort')
            for continuation in request.getContinuations():
                abort = continuation.queryInterface(abort_type)
                if abort is not None:
                    abort.select()
                    return

    return AbortInteraction()
