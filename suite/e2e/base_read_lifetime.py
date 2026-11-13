"""Finite generated-Base SELECT ownership and private-harness lifetime receipts."""
from contextlib import contextmanager
import math
import time

MAX_STAGES = 64
QUERY = 'SELECT "ID", "TEXT_VALUE", "AMOUNT" FROM "OPENGEUL_SMOKE" ORDER BY "ID"'


def _error(exc):
    value = dict(type=type(exc).__name__[:80])
    try: value['message'] = str(exc)[:256]
    except Exception: value['messageUnavailable'] = True
    return value


class LifetimeTrace:
    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.last = None
        self.receipt = dict(schemaVersion=1, kind='owned-engine-lifetime-stages', complete=True,
                            stages=[], omittedStages=0, timingErrors=[])

    def _now(self):
        try:
            value = self.clock()
            if type(value) not in (int, float) or not math.isfinite(value) or self.last is not None and value < self.last:
                raise ValueError('Invalid monotonic lifetime timestamp')
            self.last = value
            return value
        except Exception as exc:
            self.receipt['complete'] = False
            if len(self.receipt['timingErrors']) < 4:
                self.receipt['timingErrors'].append(dict(type=type(exc).__name__[:80]))
            return None

    def call(self, stage, operation, *, record_return=False):
        row = None
        if len(self.receipt['stages']) < MAX_STAGES:
            row = dict(stage=stage, startedAt=self._now(), finishedAt=None, status='started')
            self.receipt['stages'].append(row)
        else:
            self.receipt['complete'] = False
            self.receipt['omittedStages'] += 1
        try:
            value = operation()
            if row is not None:
                row['status'] = 'returned'
                if record_return:
                    row['returnType'] = type(value).__name__[:80]
                    safe = value is None or type(value) is bool or type(value) is int and -(2**63) <= value < 2**64 \
                        or type(value) is float and math.isfinite(value)
                    row['returnValueRetained'] = safe
                    if safe: row['returnValue'] = value
            return value
        except BaseException as exc:
            if row is not None:
                row.update(status='raised', errorType=type(exc).__name__[:80])
            raise
        finally:
            if row is not None: row['finishedAt'] = self._now()

    def require_complete(self):
        if not self.receipt['complete']:
            raise RuntimeError('Bounded lifetime diagnostics are incomplete')


def call(diagnostics, stage, operation):
    return operation() if diagnostics is None else diagnostics.call(stage, operation)


def preserve_cleanup_errors(primary, errors):
    """Keep the original exception object; retain every later close exception."""
    if not errors: return
    chosen = primary if primary is not None else errors[0][1]
    attributes = BaseException.__getattribute__(chosen, '__dict__')
    retained = list(attributes.get('base_cleanup_errors', ()))
    notes = list(attributes.get('__notes__', ()))
    for stage, error in errors:
        if error is not chosen: retained.append((stage, error))
        detail = _error(error)
        notes.append('Base cleanup ' + stage + ': ' + detail['type'] + ': ' + detail.get('message', '<unavailable>'))
    # Bypass any UNO exception subclass's field-specific __setattr__.
    BaseException.__setattr__(chosen, 'base_cleanup_errors', tuple(retained))
    BaseException.__setattr__(chosen, '__notes__', notes)
    if primary is None: raise chosen


def close_resources(actions, primary=None, diagnostics=None):
    errors = []
    for stage, operation in actions:
        try: call(diagnostics, stage, operation)
        except Exception as exc: errors.append((stage, exc))
    preserve_cleanup_errors(primary, errors)


@contextmanager
def resource_scope(diagnostics=None):
    actions = []
    def own(stage, operation):
        if len(actions) >= 3: raise RuntimeError('Base resource scope exceeds its fixed bound')
        actions.append((stage, operation))
    primary = None
    try: yield own
    except BaseException as exc:
        primary = exc
        raise
    finally: close_resources(reversed(actions), primary, diagnostics)


def read_rows(connection, diagnostics=None):
    with resource_scope(diagnostics) as own:
        statement = call(diagnostics, 'statement.open', connection.createStatement)
        own('statement.close', statement.close)
        result = call(diagnostics, 'statement.query', lambda: statement.executeQuery(QUERY))
        own('result.close', result.close)
        def materialize():
            rows = []
            while result.next():
                rows.append(dict(id=result.getInt(1), text=result.getString(2), amount=result.getInt(3)))
            return rows
        return call(diagnostics, 'rows.read', materialize)


def observe_database(document, diagnostics=None):
    source = document.DataSource
    with resource_scope(diagnostics) as own:
        connection = call(diagnostics, 'connection.open', lambda: source.getConnection('', ''))
        own('connection.close', connection.close)
        url = call(diagnostics, 'connection.url', lambda: source.getPropertyValue('URL'))
        return dict(databaseUrl=url, rows=read_rows(connection, diagnostics))
