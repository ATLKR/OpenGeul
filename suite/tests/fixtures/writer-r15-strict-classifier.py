"""Immutable R15 strict classifier only; current shared ports remain real.

Source a2d506812aa580c100251ae95ab8dbfe0a81d423. No engine or native stub.
"""
from writer_server_observer_runner import (DedicatedWriterRunner as _Runner, Path,
    Code, RunnerFailure, _ROLE_CODES, _UNKNOWN_IMAGE_FIELDS, _unknown_image_observation)


class DedicatedWriterRunner(_Runner):
    def _classify(self, launch, images, budget, prep, previous_roles, image_roots):
        api, handles, roles = self.c.api, [], {}
        console = self.console_profile
        prep['classificationAttemptCount'] += 1
        prep.update(classificationReasonCode=0, classificationCensusCount=None,
            classificationMatchedRoleMask=0, classificationCurrentRoleCode=0,
            classificationHistoricalRoleCode=0, classificationWaitResult=None, classificationExitCode=None,
            classificationAuxiliaryCount=0, classificationAuxiliaryCurrent=0)
        for key in _UNKNOWN_IMAGE_FIELDS: prep[key] = None
        def reject(reason):
            prep['classificationReasonCode'] = reason
            raise RunnerFailure(Code.CLASSIFICATION)
        try:
            pids = self._checked(budget, api.census, launch.job)
            if type(pids) is not tuple or len(pids) > 128 or len(set(pids)) != len(pids): reject(1)
            prep['classificationCensusCount'] = len(pids)
            if launch.identity[0] not in pids: reject(2)
            if console is not None and console.auxiliary is not None and console.auxiliary.pid not in pids: reject(11)
            for pid in pids:
                prep.update(classificationCurrentRoleCode=0, classificationHistoricalRoleCode=0,
                    classificationWaitResult=None, classificationExitCode=None, classificationAuxiliaryCurrent=0)
                handle = launch.host if pid == launch.identity[0] else (
                    console.auxiliary.handle if console is not None and console.auxiliary is not None and console.auxiliary.pid == pid else None)
                try:
                    if handle is None:
                        budget.check(observation=True)
                        handle = api.open_initial_member(pid, launch.job)
                        handles.append(handle)
                        budget.check(observation=True)
                    identity = self._checked(budget, api.identity, handle)
                    if (type(identity) is not tuple or len(identity) != 2 or identity[0] != pid or
                            not all(type(v) is int and v > 0 for v in identity)): reject(3)
                    if console is not None and console.auxiliary is not None and handle == console.auxiliary.handle:
                        if identity != (console.auxiliary.pid, console.auxiliary.birth): reject(11)
                    # Prior roles are metadata only. No historical value feeds
                    # the current image, liveness, membership or admission gate.
                    prep['classificationHistoricalRoleCode'] = next((_ROLE_CODES[name]
                        for name, original in previous_roles.items() if identity == original), 0)
                    if self._checked(budget, api.member, handle, launch.job) is not True: reject(4)
                    state = self._checked(budget, api.state, handle)
                    waited = state[0]
                    if type(state) is tuple and len(state) == 2:
                        for key, value in zip(('classificationWaitResult', 'classificationExitCode'), state):
                            if type(value) is int and 0 <= value <= 0xffffffff: prep[key] = value
                    if waited != 258: reject(5)
                    image = Path(self.c.prep.process_image(handle, check=budget.check)).resolve(strict=True)
                    role = next((name for name, expected in images.items() if image == expected), None)
                    prep['classificationCurrentRoleCode'] = _ROLE_CODES.get(role, 0)
                    if role is None:
                        if console is not None and console.matches(image, budget) and console.bind(handle, identity, launch.host):
                            prep.update(classificationAuxiliaryCount=1, classificationAuxiliaryCurrent=1)
                            continue
                        prep.update(zip(_UNKNOWN_IMAGE_FIELDS, _unknown_image_observation(image, image_roots)))
                        reject(6)
                    if role in roles: reject(7)
                    if (role == 'host') != (handle == launch.host): reject(8)
                    if role == 'host' and identity != launch.identity: reject(9)
                    roles[role] = identity
                    prep['classificationMatchedRoleMask'] |= 1 << (_ROLE_CODES[role] - 1)
                except Exception as exc:
                    retained = getattr(exc, 'retained_handle', None)
                    if retained is not None and retained not in handles: handles.append(retained)
                    raise
            return roles
        finally:
            for handle in handles:
                if console is not None and console.auxiliary is not None and handle == console.auxiliary.handle: continue
                try: closed = api.close(handle) is True
                except Exception: closed = False
                if not closed: self._private_pending.append(handle)
            if self._private_pending: raise RunnerFailure(Code.CLEANUP)
