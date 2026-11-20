"""Bounded opt-in save receipts; no request arguments or document content."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import uuid

from native_diagnostics import plain_path

MAX_RECORDS = 256
MAX_RECORD_BYTES = 4096


class SaveTrace:
    def __init__(self):
        self._lock = threading.Lock()
        self._count = 0
        self._root = self._path = None

    def record(self, event, stage, details):
        try:
            raw = os.environ.get('OPENGEUL_SUITE_DIAGNOSTICS')
            if not raw:
                return
            with self._lock:
                # Count failed/oversized attempts too: diagnostics never retry.
                self._count += 1
                if self._count > MAX_RECORDS:
                    return
                token = os.environ.get('OPENGEUL_SUITE_SAVE_TRACE_ID', '')
                trace_id = token if re.fullmatch('[a-f0-9]{32}', token) else None
                record = {'event': event, 'component': 'worker', 'stage': stage,
                          'sequence': self._count, 'utc': datetime.now(timezone.utc).isoformat(),
                          'workerPid': os.getpid(), 'threadId': threading.get_ident(),
                          'traceId': trace_id, 'details': details}
                encoded = json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n'
                # Keep recorded request IDs exact; skip an oversized record.
                if len(encoded.encode('utf-8')) > MAX_RECORD_BYTES:
                    return
                root = Path(raw)
                if (not root.is_absolute() or str(root).startswith(('\\\\', '//'))
                        or '..' in root.parts):
                    return
                plain_path(root)
                root.mkdir(parents=True, exist_ok=True)
                if root != self._root or self._path is None:
                    path = root / ('worker-save-' + str(os.getpid()) + '-' + uuid.uuid4().hex + '.jsonl')
                    with path.open('x', encoding='utf-8') as stream:
                        stream.write(encoded)
                    self._root, self._path = root, path
                else:
                    with plain_path(self._path).open('a', encoding='utf-8') as stream:
                        stream.write(encoded)
        except Exception:
            # A receipt must never change dispatch, storage, or the JSONL reply.
            pass


_trace = SaveTrace()


def trace_request(stage, request_id, *, ok=None, error_code=None, exception_type=None):
    details = {'requestId': request_id}
    if ok is not None:
        details['ok'] = ok
    if error_code is not None:
        details['errorCode'] = error_code
    if exception_type is not None:
        details['exceptionType'] = exception_type
    _trace.record('suite.workerSave', stage, details)


def trace_native_dispatch(sequence, command, native_command):
    _trace.record('suite.nativeDispatch', 'received',
                  {'receiptSequence': sequence, 'command': command, 'nativeCommand': native_command})


def trace_calc_save(stage, command, *, state=None, result=None, exception_type=None):
    details = {'nativeCommand': command}
    if state is not None:
        details['dispatchState'] = state
    if result is not None:
        details['dispatchResult'] = result
    if exception_type is not None:
        details['exceptionType'] = exception_type
    _trace.record('suite.calcNativeSave', stage, details)
