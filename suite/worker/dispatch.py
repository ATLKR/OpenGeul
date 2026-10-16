"""Route native document-management actions back to the owning Suite form."""
COMMANDS = {'.uno:Open': 'open', '.uno:OpenUrl': 'open', '.uno:OpenRemote': 'open',
            '.uno:NewDoc': 'new', '.uno:NewWindow': 'new', '.uno:Save': 'save',
            '.uno:SaveAll': 'save', '.uno:SaveAs': 'saveAs', '.uno:SaveAsTemplate': 'saveAs',
            '.uno:SaveACopy': 'saveAs', '.uno:SaveAsRemote': 'saveAs',
            '.uno:CloseDoc': 'close', '.uno:CloseWin': 'close', '.uno:CloseFrame': 'close', '.uno:Quit': 'close',
            '.uno:Exit': 'close'}


class DispatchRouter:
    def __init__(self, on_command):
        self.on_command = on_command
        self.slave = None
        self.master = None

    def queryDispatch(self, url, target, flags):
        name = url.Complete.split('?', 1)[0]
        if name in COMMANDS or name.startswith(('private:factory/', 'file:')):
            return self
        if self.slave is not None and self.slave is not self:
            return self.slave.queryDispatch(url, target, flags)
        return None

    def queryDispatches(self, descriptors):
        return tuple(self.queryDispatch(d.FeatureURL, d.FrameName, d.SearchFlags) for d in descriptors)

    def dispatch(self, url, arguments):
        name = url.Complete.split('?', 1)[0]
        command = ('new' if name.startswith('private:factory/') else
                   'open' if name.startswith('file:') else COMMANDS.get(name))
        if command:
            self.on_command(command)

    def addStatusListener(self, listener, url):
        # Keep native buttons enabled. The shell owns the actual decision/action.
        try:
            import uno
            event = uno.createUnoStruct('com.sun.star.frame.FeatureStateEvent')
            event.Source, event.FeatureURL, event.IsEnabled = self, url, True
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
        return tuple(COMMANDS) + ('private:factory/*', 'file:*')


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
