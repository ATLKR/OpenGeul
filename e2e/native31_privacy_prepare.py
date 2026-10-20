"""Explicit CI-only privacy preparation; no other OS window close is exposed.

The unmodified legacy primitive supplies one WM_CLOSE plus bounded dismissal
polling. Instance adapters supply strict full-schema observations and audit the
single native send boundary; they never change legacy module globals.
"""
import ctypes
import importlib.util
import io

WINDOW_FIELDS = ('hwnd', 'processId', 'threadId', 'title', 'className', 'visible', 'enabled', 'rectangle')


def movement_count(receipt):
    # The original function finalizes this receipt in finally. Presence is the
    # retained boundary immediately before its single unchanged setter path.
    return int('beforePhysicalPoint' in receipt)


def preparation_receipt(core, evidence):
    """Conservative action accounting also works after an owned-observer timeout."""
    result = core.flags(prepare_privacy=True)
    path = evidence.path / 'p49-preparation.json'
    if path.exists():
        try:
            result, _ = core.legacy.bounded_object(path)
            for key in ('readOnly', 'diagnosticOnly', 'readiness', 'hostReadyQualified',
                        'productQualified', 'productExecuted', 'consentActions'):
                core.require(result.get(key) == core.flags(prepare_privacy=True)[key], 'Invalid preparation receipt flags')
            core.require(result.get('closeRequests') in (0, 1) and result.get('physicalPointerGateInvocations') in (0, 1)
                         and result.get('inputsPerformed') in (None, 0, 1), 'Invalid preparation receipt counts')
            core.require(not result.get('privacyPreparationQualified') or
                         (result.get('physicalTaskbarGatePassed') is True and result.get('inputsPerformed') == 1
                          and result.get('physicalPointerGateInvocations') == 1 and 'failure' not in result),
                         'Invalid successful preparation receipt')
            return result
        except Exception as exc:
            result = core.flags(prepare_privacy=True)
            result['preparationReceiptFailure'] = core.error_record(exc)
    for name, kind in [('p21-close-intent', 'WM_CLOSE'), ('p40-pointer-intent', 'physical-taskbar-gate')]:
        path = evidence.path / (name + '.json')
        if path.exists():
            intent, _ = core.legacy.bounded_object(path)
            result['actions'].append(intent)
            if kind == 'WM_CLOSE': result['closeRequests'] = 1
            else:
                result['physicalPointerGateInvocations'] = 1
                result['inputsPerformed'] = None
                result['inputCountStatus'] = 'unknown: no finalized original pointer receipt'
                result['inputAttemptBounds'] = [0, 1]
                pointer = evidence.path / 'p41-original-pointer.json'
                if pointer.exists():
                    try:
                        receipt, _ = core.legacy.bounded_object(pointer)
                        core.require(type(receipt.get('success')) is bool, 'Incomplete original pointer receipt')
                        result['inputsPerformed'] = movement_count(receipt)
                        result['inputCountStatus'] = 'inferred from finalized original beforePhysicalPoint boundary'
                        result['inputAttemptBounds'] = [result['inputsPerformed']] * 2
                    except Exception as exc:
                        result['pointerReceiptFailure'] = core.error_record(exc)
    return result


def finalize_preparation(core, evidence, result):
    """Preserve child action evidence, but qualification also needs controller success."""
    preparation = preparation_receipt(core, evidence)
    if 'failure' in preparation:
        preparation['preparationFailure'] = preparation.pop('failure')
    result.update(preparation)
    qualified = (result['success'] and result.get('naturalExit') is True and result.get('exitCode') == 0
        and not result.get('forced') and not result.get('timedOut') and not result.get('cleanupFailure')
        and not result.get('cleanupQueryFailure') and preparation['privacyPreparationQualified'])
    result['privacyPreparationQualified'] = bool(qualified)
    result['success'] = bool(qualified)


class PreparationSession:
    def __init__(self, core, probe, evidence, budget, controller, classification, *, source_receipt=None):
        self.c, self.probe, self.evidence, self.budget = core, probe, evidence, budget
        self.controller, self.classification = controller, classification
        self.source_receipt = source_receipt
        self.actions = []; self.close_requests = 0; self.pointer_invocations = 0
        self.inputs = 0; self.pointer_passed = False

    def summary(self, *, qualified=False):
        return {**self.c.flags(prepare_privacy=True), 'actions': list(self.actions),
                'closeRequests': self.close_requests, 'physicalPointerGateInvocations': self.pointer_invocations,
                'inputsPerformed': self.inputs,
                'inputCountStatus': ('unknown: no finalized original pointer receipt' if self.inputs is None else
                    'inferred from finalized original beforePhysicalPoint boundary' if self.pointer_invocations else 'pointer gate not invoked'),
                'inputAttemptBounds': [0, 1] if self.inputs is None else [self.inputs, self.inputs],
                'privacyPreparationQualified': qualified,
                'physicalTaskbarGatePassed': self.pointer_passed,
                'initialPrivacyObservation': self.classification.get('status')}

    def identity_source(self):
        self.budget.remaining(3)
        initial, _ = self.c.legacy.bounded_object(self.evidence.path / '32-observer-context.json')
        host, _ = self.c.legacy.bounded_object(self.evidence.path / '31-observer-host.json')
        current = self.probe.identity(); self.c.same_host(host, current)
        self.c.require(current['processId'] == host['processId'] and current['process'] == host['process'],
                       'Preparation observer identity changed')
        source = self.source_receipt(self.budget) if self.source_receipt else self.c.source_receipt(self.budget)
        self.c.require(source == initial['source'] and source['files'] == self.controller['sourceFiles'],
                       'Preparation source changed')
        return {'host': current, 'source': source, 'deadlineMonotonic': self.budget.deadline}

    def close(self, candidate):
        self.c.require(candidate.get('kind') == 'WWAHost.exe' and candidate.get('operation') == 'WM_CLOSE',
                       'Only the exact privacy candidate may be closed')
        self.c.require(self.close_requests == 0, 'No second privacy close request')
        adapter = PrivacyAdapter(self, candidate)
        primary = None
        try:
            # Reserve the existing primitive's 3-second send and 10-second dismissal
            # sublimits inside the one original controller deadline/reserve.
            self.budget.remaining(16)
            result = self.c.legacy.WindowsProbe.close_verified(adapter, candidate)
            self.evidence.write('p23-close-result', result)
            confirmed = (result['messageRequests'] == self.close_requests == 1
                and result['messageDelivered'] and result['surfaceDismissed']
                and not result['ownershipChangedAfterSend'] and result['postSendErrorType'] is None
                and result['afterHandleReleaseState'] and result['afterHandleReleaseState']['surfaceDismissed'])
            if not confirmed:
                if adapter.state_exception is not None: raise adapter.state_exception
                raise ValueError('Single privacy close did not establish verified dismissal')
            self.budget.remaining(3)
            return result
        except Exception as exc:
            primary = exc
            raise
        finally:
            failures = adapter.cleanup_failures
            try:
                self.evidence.write('p24-close-cleanup', {'primaryFailure': self.c.error_record(primary) if primary else None,
                                                        'cleanupFailures': failures})
            except Exception as exc:
                failures.append({'stage': 'close-cleanup-receipt', **self.c.error_record(exc)})
            if failures:
                if primary is not None:
                    primary.cleanup_failures = getattr(primary, 'cleanup_failures', []) + failures
                else:
                    error = ValueError('Privacy close query handle cleanup failed')
                    error.cleanup_failures = failures
                    raise error

    def post_state(self):
        c, probe, out = self.c, self.probe, self.evidence
        self.budget.remaining(3)
        with c.physical_queries(probe, out, 'p33-post-dpi'):
            census, errors, enumerated = probe.census()
            out.write('p31-post-census', {**census, 'errors': errors, 'enumerationSucceeded': enumerated})
            c.validate_census(census)
            c.require(enumerated and not errors and not census['truncated'], 'Post-state census incomplete')
            hit = probe.taskbar()
            targets = [probe.target(hwnd) for hwnd in dict.fromkeys(
                [census['foregroundHwnd'], hit['actualPointHwnd'], hit['actualRootHwnd']])]
            out.write('p32-post-hit', {'physicalHit': hit, 'targets': targets})
        with c.physical_queries(probe, out, 'p36-post-screen-dpi'):
            out.write('p34-post-screen-before', {'stage': 'before-capture'})
            from PIL import ImageGrab
            screen = ImageGrab.grab(all_screens=False)
            c.require(0 < screen.width <= 8192 and 0 < screen.height <= 8192 and screen.width * screen.height <= 20_000_000,
                      'Post-state screenshot pixel bound exceeded')
            stream = io.BytesIO(); screen.save(stream, format='PNG'); data = stream.getvalue()
            c.require(8 <= len(data) <= 8 * 1024 * 1024, 'Post-state screenshot byte bound exceeded')
            with (out.path / 'privacy-post-desktop.png').open('xb') as target: target.write(data)
            out.write('p35-post-screen-after', {'width': screen.width, 'height': screen.height,
                'bytes': len(data), 'sha256': c.hashlib.sha256(data).hexdigest()})
        out.write('p37-post-source-host', self.identity_source())

    def pointer(self):
        c = self.c
        c.require(self.pointer_invocations == 0, 'Original pointer gate may run only once')
        self.budget.remaining(3)
        # Exact source module and function; no replacement probe, monkeypatch, or retry.
        path = c.ROOT / 'suite/e2e/native_window_evidence.py'
        spec = importlib.util.spec_from_file_location('native31_original_pointer_gate', path)
        gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
        self.pointer_invocations = 1
        intent = {'operation': 'physical-taskbar-gate', 'invocations': 1, 'pointerMoveAttempted': None,
                  'deadlineMonotonic': self.budget.deadline, 'sourceSha256': c.hashlib.sha256(path.read_bytes()).hexdigest()}
        self.actions.append(intent)
        self.evidence.write('p40-pointer-intent', intent)
        self.inputs = None  # Unknown until the unmodified gate's own receipt is available.
        primary = None; receipt = None
        try:
            receipt = gate.prepare_launch_pointer(self.evidence.path, 'p41-original')
            c.require(receipt['success'] is True and movement_count(receipt) == 1, 'Original pointer gate did not pass')
            self.budget.remaining(3)
            self.pointer_passed = True
        except Exception as exc:
            primary = exc
            raise
        finally:
            try:
                if receipt is None and (self.evidence.path / 'p41-original-pointer.json').exists():
                    receipt, _ = c.legacy.bounded_object(self.evidence.path / 'p41-original-pointer.json')
                if receipt is not None:
                    # Original source writes this immediately before SetPhysicalCursorPos.
                    attempted = 'beforePhysicalPoint' in receipt
                    self.inputs = movement_count(receipt)
                    intent['pointerMoveAttempted'] = attempted
                    intent['movementEvidenceBasis'] = 'movement attempt inferred from finalized original beforePhysicalPoint boundary'
                    intent['inputAttemptBounds'] = [self.inputs, self.inputs]
                self.evidence.write('p42-pointer-result', {'receipt': receipt, 'inputsPerformed': self.inputs,
                    'failure': c.error_record(primary) if primary else None, 'physicalTaskbarGatePassed': self.pointer_passed})
            except Exception as cleanup:
                if primary is not None:
                    primary.cleanup_failures = getattr(primary, 'cleanup_failures', []) + [c.error_record(cleanup)]
                else: raise
        self.evidence.write('p46-final-source-host', self.identity_source())
        self.budget.remaining(3)
        return self.summary(qualified=True)

    def run(self):
        primary = None; result = None
        try:
            self.budget.remaining(3)
            status = self.classification.get('status')
            self.c.require(status in ('privacy-match', 'privacy-absent-observed'), 'No complete initial privacy observation')
            self.evidence.write('p05-preparation-decision', {'initialStatus': status, **self.summary()})
            if status == 'privacy-match': self.close(self.classification['candidate'])
            self.post_state()
            result = self.pointer()
            return result
        except Exception as exc:
            primary = exc
            raise
        finally:
            receipt = result if result is not None else self.summary()
            if primary is not None: receipt['failure'] = self.c.error_record(primary)
            try:
                self.evidence.write('p49-preparation', receipt)
            except Exception as cleanup:
                if primary is not None:
                    primary.cleanup_failures = getattr(primary, 'cleanup_failures', []) + [self.c.error_record(cleanup)]
                else: raise


class PrivacyAdapter:
    """Strict, instance-scoped input to unchanged close_verified; privacy only."""
    def __init__(self, session, candidate):
        self.session, self.probe, self.candidate = session, session.probe, candidate
        self.c, self.out, self.budget = session.c, session.evidence, session.budget
        self.cleanup_failures = []; self.held = None; self.last_state = None; self.state_exception = None
        self.user = SendBoundary(self)
        self.kernel = HeldKernel(self)
        self.dwm = self.probe.dwm

    def session_id(self): return self.probe.session_id()
    def windows_directory(self): return self.probe.windows_directory()

    def current(self, hwnd):
        c, probe, out = self.c, self.probe, self.out
        c.require(hwnd == self.candidate['hwnd'], 'Privacy refresh HWND mismatch')
        self.budget.remaining(16)
        out.write('p10-fresh-before', {'hwnd': hwnd, 'deadlineMonotonic': self.budget.deadline})
        with c.physical_queries(probe, out, 'p12-fresh-dpi'):
            census, errors, enumerated = probe.census()
            target = probe.target(hwnd)
            out.write('p11-fresh-native', {'census': census, 'errors': errors, 'enumerationSucceeded': enumerated, 'target': target})
            c.validate_census(census)
            c.require(enumerated and not errors and not census['truncated'] and census['foregroundHwnd'] == hwnd,
                      'Fresh privacy census incomplete or foreground changed')
            window = {key: target[key] for key in WINDOW_FIELDS}
            c.require(window == next(row for row in census['windows'] if row['hwnd'] == hwnd)
                      and window == self.candidate['window'], 'Fresh privacy window metadata changed')
        handle = probe.kernel.OpenProcess(0x1000, False, window['processId'])
        c.require(handle, 'Fresh privacy process query denied')
        primary = None
        try:
            process = probe.process_identity(handle, window['processId'])
            out.write('p13-fresh-process', process)
            c.require(process['sessionId'] == self.session_id(), 'Fresh privacy session mismatch')
            process.update(c.image_receipt(process['imagePath'], self.budget))
            out.write('p14-fresh-image', process)
            process['signature'] = c.signatures([process['imagePath']], self.budget)[0]
            out.write('p15-fresh-signature', process)
            out.write('p16-fresh-uia-before', {'hwnd': hwnd, 'stage': 'before-COM'})
            tree = probe.strict_uia(hwnd)
            out.write('p17-fresh-uia-after', tree)
            if 'error' in tree:
                raise c.diagnostic_error('Fresh privacy UIA failed: ' + tree['error'].get('message', 'unavailable property'), uiaFailure=tree['error'])
            c.validate_diagnostic_uia(tree, hwnd)
            c.require('error' not in tree and not tree['truncated'] and tree['nodes']
                      and all(node['processId'] == window['processId'] for node in tree['nodes']),
                      'Fresh privacy UIA incomplete or foreign-owned')
            with c.physical_queries(probe, out, 'p19-fresh-dpi'):
                refreshed = probe.target(hwnd)
                state = probe.process_identity(handle, window['processId'])
                c.require(int(probe.user.GetForegroundWindow() or 0) == hwnd and refreshed == target
                    and all(process[key] == value for key, value in state.items()), 'Fresh privacy identity raced')
                source_host = self.session.identity_source()
                observed = {'foreground': window, 'processes': [process], 'uia': [tree]}
                out.write('p18-fresh-recheck', {'observation': observed, 'target': refreshed, 'heldProcess': state, **source_host})
            # Full process fields (including exitCode/peMachine) and full UIA names
            # are retained; the unchanged primitive compares this exact schema.
            c.legacy.privacy_candidate(observed, self.session_id(), self.windows_directory())
            self.budget.remaining(16)
            return observed
        except Exception as exc:
            primary = exc
            raise
        finally:
            try:
                c.require(probe.kernel.CloseHandle(handle), 'Fresh process handle close failed')
            except Exception as cleanup:
                self.cleanup_failures.append({'stage': 'fresh-process-handle', **c.error_record(cleanup)})
                if primary is None: raise

    def checked_state(self, handle):
        state = self.probe.startup_process_state(handle, self.candidate['process']['processId'])
        p = self.candidate['process']
        self.c.require(all(state[key] == p[key] for key in ('createdFileTime', 'processMachine', 'nativeMachine', 'sessionId'))
            and state['sessionId'] == self.session_id(), 'Held privacy identity/session changed')
        return state

    def window_state(self, candidate, held_handle):
        self.budget.remaining(3)
        self.c.require(candidate is self.candidate, 'Unexpected close candidate')
        extra = None; primary = None
        try:
            exists = bool(self.probe.user.IsWindow(candidate['hwnd']))
            if held_handle:
                self.checked_state(held_handle)
            elif exists:
                extra = self.probe.kernel.OpenProcess(0x1000, False, candidate['process']['processId'])
                self.c.require(extra, 'Post-release privacy identity unavailable')
                self.checked_state(extra)
            handle = held_handle or extra
            state = self.c.legacy.WindowsProbe.window_state(self, candidate, handle)
            if handle:
                self.c.require(state['heldCreationFileTime'] == candidate['process']['createdFileTime']
                    and state['heldProcessMachine'] == 0 and state['heldNativeMachine'] == 0xAA64,
                    'Dismissal held identity query failed')
            if state['windowExists']:
                self.c.require(state['dwmHresult'] == '0x00000000' and state['cloakedBits'] is not None,
                               'Privacy DWM state query unavailable')
                self.c.require(state['title'] == self.probe.text_value(candidate['hwnd'])
                    and state['className'] == self.probe.text_value(candidate['hwnd'], True), 'Privacy window text raced/truncated')
                self.c.require(state['ownerMatches'], 'Privacy HWND ownership changed')
            else:
                self.c.require(state['foregroundHwnd'] != candidate['hwnd'], 'Destroyed privacy HWND remains foreground')
            self.last_state = state
            return state
        except Exception as exc:
            primary = exc
            self.state_exception = exc
            raise
        finally:
            if extra:
                try:
                    self.c.require(self.probe.kernel.CloseHandle(extra), 'Post-release handle close failed')
                except Exception as cleanup:
                    self.cleanup_failures.append({'stage': 'post-release-handle', **self.c.error_record(cleanup)})
                    if primary is None: raise


class HeldKernel:
    def __init__(self, adapter): self.adapter = adapter
    def __getattr__(self, name): return getattr(self.adapter.probe.kernel, name)
    def OpenProcess(self, access, inherit, pid):
        a = self.adapter
        a.c.require(access == 0x1000 and not inherit and pid == a.candidate['process']['processId'], 'Unexpected close query handle request')
        handle = a.probe.kernel.OpenProcess(access, inherit, pid)
        if handle: a.held = handle
        return handle
    def CloseHandle(self, handle):
        a = self.adapter
        try:
            result = a.probe.kernel.CloseHandle(handle)
            a.c.require(result, 'Held close-query handle release failed')
        except Exception as cleanup:
            result = False
            a.cleanup_failures.append({'stage': 'legacy-held-handle', **a.c.error_record(cleanup)})
        if handle == a.held: a.held = None
        return result


class SendBoundary:
    def __init__(self, adapter): self.adapter = adapter
    def __getattr__(self, name): return getattr(self.adapter.probe.user, name)
    def SendMessageTimeoutW(self, hwnd, message, wparam, lparam, flags, timeout, result):
        a = self.adapter; session = a.session
        a.c.require((hwnd, message, wparam, lparam, flags, timeout) ==
                    (a.candidate['hwnd'], 0x0010, 0, 0, 0x0002, 3000), 'Only the fixed privacy WM_CLOSE is permitted')
        a.c.require(session.close_requests == 0 and a.held, 'Duplicate or unowned privacy close')
        a.budget.remaining(16)
        with a.c.physical_queries(a.probe, a.out, 'p20-before-send-dpi'):
            window = a.probe.window(hwnd)
            held = a.checked_state(a.held)
            a.c.require(held['exitCode'] == 259 and window == a.candidate['window']
                        and int(a.probe.user.GetForegroundWindow() or 0) == hwnd, 'Privacy identity changed at send boundary')
        a.budget.remaining(16)
        session.close_requests = 1
        intent = {'operation': 'WM_CLOSE', 'message': 0x0010, 'request': 1, 'hwnd': hwnd,
                  'processId': a.candidate['process']['processId'], 'createdFileTime': held['createdFileTime'],
                  'heldHandle': int(a.held), 'beforeNativeState': a.last_state, 'deadlineMonotonic': a.budget.deadline}
        session.actions.append(intent)
        a.out.write('p21-close-intent', intent)
        try:
            delivered = a.probe.user.SendMessageTimeoutW(hwnd, message, wparam, lparam, flags, timeout, result)
            a.out.write('p22-close-delivery', {'messageDelivered': bool(delivered), 'messageResult': int(result._obj.value),
                       'lastError': getattr(ctypes, 'get_last_error', lambda: None)() if not delivered else None})
            return delivered
        except Exception as exc:
            try:
                a.out.write('p22-close-delivery', {'messageDelivered': None, 'failure': a.c.error_record(exc)})
            except Exception as cleanup:
                exc.cleanup_failures = getattr(exc, 'cleanup_failures', []) + [a.c.error_record(cleanup)]
            raise
