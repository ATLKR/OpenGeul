"""Explicit owned Calc close preparation, never a read-only status operation.

AcceptFormula submits ordinary input through Calc's normal entry path. Its void
dispatch result does not prove asynchronous validation/formula completion, and a
clean model does not prove that no buffer remains. Every Calc close therefore
still requires the Suite's explicit Save/Discard/Cancel choice. No file is
stored and no native picker or interactive close transaction is started here.
"""
from session import WorkerError

COMMAND = '.uno:AcceptFormula'


def _failed():
    return WorkerError('close_failed', 'Calc 입력과 문서 소유권을 확인하지 못했습니다. 문서를 열어 둡니다.')


def prepare_calc_close(transaction):
    """Run once only when the owning shell explicitly starts closing its Calc."""
    if transaction is None or transaction.saving or getattr(transaction, '_preparing_close', False):
        raise _failed()
    transaction._preparing_close = True
    try:
        transaction._owned()
        backend = transaction.backend
        document, frame, controller = transaction.document, transaction.frame, transaction.controller
        original_url = document.getURL()
        before = document.isModified()
        if type(before) is not bool:
            raise _failed()
        frame.activate()
        transaction._owned()
        if not frame.isActive():
            raise _failed()
        url = backend.uno.createUnoStruct('com.sun.star.util.URL')
        url.Complete, url.Protocol, url.Path = COMMAND, '.uno:', 'AcceptFormula'
        # The retained controller resolves its native Calc view slot; querying
        # the frame would pass through Suite document-management interception.
        dispatch = controller.queryDispatch(url, '_self', 0)
        if dispatch is None or not callable(getattr(dispatch, 'dispatchWithNotification', None)):
            raise _failed()
        helper = transaction._service('com.sun.star.frame.DispatchHelper')
        result = helper.executeDispatch(controller, COMMAND, '_self', 0,
                                        (backend._property('OnMainThread', True),))
        transaction._owned()
        if not frame.isActive() or document.getURL() != original_url:
            raise _failed()
        # This void slot does not supply Done()/a semantic result item. A native
        # FAILURE notification can follow ordinary successful input acceptance.
        # Preserve it as dispatch evidence, never as a commit/veto oracle.
        state = getattr(result, 'State', None)
        if type(state) is not int or state not in (0, 1) or getattr(result, 'Result', object()) is not None:
            raise _failed()
        after = document.isModified()
        if type(after) is not bool:
            raise _failed()
        return dict(modified=True, nativeModified=after, title=str(document.getTitle()),
                    closePreparation=dict(command=COMMAND, onMainThread=True,
                        nativeCommandReturned=True, nativeDispatchState=state, nativeDispatchResult=None,
                        nativeModifiedBefore=before, nativeModifiedAfter=after,
                        requiresExplicitChoice=True, pendingInputAbsenceVerified=False,
                        asyncValidationQualified=False))
    except WorkerError as exc:
        if exc.code == 'close_failed': raise
        raise _failed() from exc
    except Exception as exc:
        raise _failed() from exc
    finally:
        transaction._preparing_close = False
