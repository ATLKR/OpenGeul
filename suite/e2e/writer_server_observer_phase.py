"""Bounded fresh-environment Python phase; original engine authority stays inside.

The wrapper's retained child exit is never original-engine remote retirement.
Compiler preparation may copy its already restricted child environment. No
ambient environment is enumerated or copied here. Native synchronous calls
are checked on return and are not claimed to be preemptible.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import time

_PENDING=[]


def _receipt():
    return dict(schemaVersion=1,passed=False,launchAttempted=False,originalChildIdentityMatched=False,
        originalChildExitObserved=False,originalChildExitCode=None,ownedJobEmpty=None,forcedDisposalRequested=False,
        timedOut=False,cleanupComplete=False,pendingRetainedCount=0,errorCode=0,
        originalEngineRetirementAuthority=False,normalAcceptance=False,fullEngineQualified=False,
        acceptanceEligible=False,guiVerified=False,hardDeadlineEnforcementVerified=False)


def run_phase(*,api,runtime,child_arguments,seconds,read_value,environment_builder,descriptor_factory,pause=time.sleep):
    receipt=_receipt();owned=controller=None;pending=[];start=cutoff=deadline=frequency=last=None
    controller_identity=original_identity=None;invalid_clock=False;deadline_closed=False
    def sample(*,cleanup=False):
        nonlocal last,invalid_clock,deadline_closed
        if invalid_clock:raise ValueError()
        if deadline_closed:raise TimeoutError()
        try:
            now=api.qpc_read()
            if (invalid_clock or type(now) is not int or now<=0 or now>(1<<63)-1 or
                    (last is not None and now<last) or api.qpc_frequency()!=frequency):raise ValueError()
        except Exception:
            invalid_clock=True;raise ValueError() from None
        last=now
        if now>=deadline:deadline_closed=True;raise TimeoutError()
        if now>=(deadline if cleanup else cutoff):raise TimeoutError()
        return now
    def within():
        try:sample(cleanup=True);return True
        except Exception:return False
    def observe():
        sample(cleanup=True)
        same=api.identity(owned.host)==original_identity
        sample(cleanup=True)
        receipt['originalChildIdentityMatched']=same
        if not same:raise ValueError()
        state=api.state(owned.host)
        observed=sample(cleanup=True)
        if type(state) is not tuple or len(state)!=2 or state[0] not in (0,258) or type(state[1]) is not int or not 0<=state[1]<=0xffffffff:raise ValueError()
        if state[0]==0:
            receipt['originalChildExitObserved']=True;receipt['originalChildExitCode']=state[1]
            return True
        return False
    try:
        if type(seconds) is not int or not 5<seconds<=1200 or _PENDING:raise ValueError()
        frequency=api.qpc_frequency();start=api.qpc_read();last=start
        if type(frequency) is not int or frequency<=0 or type(start) is not int or start<=0 or start+seconds*frequency>(1<<63)-1:raise ValueError()
        cutoff=start+(seconds-5)*frequency;deadline=start+seconds*frequency
        sample()
        controller,controller_identity=api.retain_current_controller()
        sample()
        descriptor=descriptor_factory(*controller_identity,secrets.randbelow((1<<64)-1)+1)
        environment=environment_builder(read_value,runtime,descriptor)
        sample()
        receipt['launchAttempted']=True
        owned=api.launch([str(runtime.host_python),'-B','-E','-s',str(runtime.helper_script),'--child',*child_arguments],
            str(runtime.helper_script.parent),environment,controller_binding=(controller,controller_identity,descriptor.nonce))
        original_identity=owned.identity
        sample()
        if (owned.failed is not False or owned.uncertain is not False or owned.resumed is not True or
                owned.creation_job_membership is not True or owned.pre_resume_verified is not True):raise ValueError()
        for _ in range(120000):
            sample()
            if observe():break
            pause(min(.02,(cutoff-sample())/frequency))
        else:raise TimeoutError()
        sample()
        receipt['ownedJobEmpty']=api.census(owned.job)==()
        sample()
        receipt['passed']=receipt['originalChildExitCode']==0 and receipt['ownedJobEmpty'] is True
    except Exception as exc:
        receipt['errorCode']=2 if isinstance(exc,TimeoutError) else 1
        receipt['timedOut']=isinstance(exc,TimeoutError)
        retained=getattr(exc,'retained_handle',None)
        if retained is not None:pending.append(retained)
    finally:
        complete=True
        if owned is not None:
            if not receipt['originalChildExitObserved'] or receipt['ownedJobEmpty'] is not True:
                before=within()
                if before:
                    try:receipt['forcedDisposalRequested']=api.terminate_job(owned.job) is True
                    except Exception:complete=False
                    complete=within() and complete
                else:complete=False
            if original_identity is not None and not receipt['originalChildExitObserved'] and within():
                for _ in range(120000):
                    try:
                        if observe():break
                        pause(min(.01,(deadline-sample(cleanup=True))/frequency))
                    except Exception:break
            before=within()
            local_ok=False
            if before:
                try:local_ok=api.release_launch_local(owned) is True
                except Exception:local_ok=False
                complete=within() and local_ok and complete
            else:complete=False
            if not local_ok:pending.append(owned)
            for handle in (owned.thread,owned.host if receipt['originalChildExitObserved'] else None,owned.job):
                if handle is None:continue
                before=within()
                closed=False
                if before:
                    try:closed=api.close(handle) is True
                    except Exception:closed=False
                    complete=within() and closed and complete
                else:complete=False
                if not closed:pending.append((handle,owned))
            if not receipt['originalChildExitObserved'] and owned.host is not None:pending.append((owned.host,owned))
        if controller is not None:
            if pending:pending.append((controller,controller_identity))
            else:
                before=within()
                closed=False
                if before:
                    try:closed=api.close(controller) is True
                    except Exception:closed=False
                    complete=within() and closed and complete
                else:complete=False
                if not closed:pending.append((controller,controller_identity))
        if pending:_PENDING.append((api,owned,controller,tuple(pending)))
        receipt['pendingRetainedCount']=len(pending)
        receipt['cleanupComplete']=complete and not pending and owned is not None
        receipt['passed']=receipt['passed'] and receipt['cleanupComplete'] and not receipt['timedOut']
    return receipt


class Parser(argparse.ArgumentParser):
    def error(self,message):raise ValueError()


def _save(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='ascii') as stream:json.dump(value,stream,separators=(',',':'),sort_keys=True)


def build_atomic_environment(read_value,runtime,descriptor):
    """Add one validated machine-folder key needed by Setup Configuration COM.

    The observation helper retains its original fresh environment. Neither the
    ambient PATH nor any other ambient key is copied into this compiler child.
    """
    from writer_server_observer_msaa import build_host_environment
    result=build_host_environment(read_value,runtime,descriptor)
    try:
        value=read_value('ProgramData')
        if (type(value) is not str or not 0<len(value)<=32767 or
                any(char in value for char in '\0\r\n"%;!&|<>^')):raise ValueError()
        path=Path(value)
        if not path.is_absolute() or '..' in path.parts:raise ValueError()
        for part in reversed((path,*path.parents)):
            info=part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&1024:raise ValueError()
        if not stat.S_ISDIR(info.st_mode):raise ValueError()
        result['ProgramData']=str(path.resolve(strict=True))
    except Exception:raise ValueError() from None
    return result


def atomic_failure_exit(error):
    """Report only a builtin kind and deepest fixed-source coordinate.

    This is a nonzero child status, not a compiler/native error code or an
    engine-retirement witness. No exception arguments, locals, messages, log
    files or environment values are inspected. Unknown/truncated traces retain
    the original generic failure status. Bits: 0x5A, kind4, file4, line16.
    """
    kinds={AssertionError:1,OSError:2,FileNotFoundError:3,PermissionError:4,
        ValueError:5,TypeError:6,RuntimeError:7,TimeoutError:8,ImportError:9,
        ModuleNotFoundError:10,OverflowError:11,UnicodeDecodeError:12}
    kind=kinds.get(type(error))
    if kind is None:return 3
    try:
        root=Path(__file__).resolve().parent
        sources={str(root/'writer_server_observer_phase.py'):1,
            str(root/'ascii_message_preparation.py'):2,
            str(root/'native_compiler_tools.py'):3,
            str(root/'native_suite_architecture.py'):4,
            str(root.parent/'worker/native_windows.py'):5}
        frame=BaseException.__getattribute__(error,'__traceback__')
        deepest=None;seen=0
        while frame is not None and seen<64:
            file=sources.get(frame.tb_frame.f_code.co_filename)
            if file is not None:
                line=frame.tb_lineno
                if type(line) is not int or not 1<=line<=20000:return 3
                deepest=(file,line)
            frame=frame.tb_next;seen+=1
        if frame is not None or deepest is None:return 3
        file,line=deepest
        return 0x5A000000|(kind<<20)|(file<<16)|line
    except BaseException:return 3


def child(arguments):
    # This entry is only invoked by the parent wrapper's creation-owned NUL
    # launch, with the named-key fresh environment. It performs no host copy.
    try:
        if arguments and arguments[0]=='atomic':
            parser=Parser(add_help=False,allow_abbrev=False);parser.add_argument('--work',required=True);parser.add_argument('--descriptor',required=True)
            args=parser.parse_args(arguments[1:])
            from ascii_message_preparation import prepare_observer
            descriptor=prepare_observer(Path(args.work).resolve(),architecture='arm64',discovery_policy='installed-native')
            _save(args.descriptor,descriptor);return 0
        if arguments and arguments[0]=='observe':
            from writer_server_observer_runner import main
            return main(arguments[1:])
        return 3
    except BaseException as error:
        return atomic_failure_exit(error) if arguments and arguments[0]=='atomic' else 3


def main(arguments=None):
    args=sys.argv[1:] if arguments is None else arguments
    if args and args[0]=='--child':return child(args[1:])
    receipt=_receipt();report=None
    try:
        parser=Parser(add_help=False,allow_abbrev=False)
        for name in ('host-python','windows','temp','office-program','seconds','receipt'):parser.add_argument('--'+name,required=True)
        parser.add_argument('child_arguments',nargs=argparse.REMAINDER)
        parsed=parser.parse_args(args);report=Path(parsed.receipt)
        if not parsed.seconds.isdecimal() or str(int(parsed.seconds))!=parsed.seconds:raise ValueError()
        from writer_server_observer_win32 import NativeApi
        from writer_server_observer_capture import Descriptor
        from writer_server_observer_msaa import HostRuntime,build_host_environment
        runtime=HostRuntime.validated(Path(parsed.host_python),Path(__file__).resolve(),Path(parsed.windows),Path(parsed.temp),
            Path(parsed.office_program))
        child_arguments=parsed.child_arguments[1:] if parsed.child_arguments[:1]==['--'] else parsed.child_arguments
        if not child_arguments or child_arguments[0] not in ('atomic','observe'):raise ValueError()
        environment_builder=build_atomic_environment if child_arguments[0]=='atomic' else build_host_environment
        receipt=run_phase(api=NativeApi(),runtime=runtime,child_arguments=child_arguments,
            seconds=int(parsed.seconds),read_value=lambda key:os.environ.get(key),
            environment_builder=environment_builder,descriptor_factory=Descriptor)
    except BaseException:receipt['errorCode']=1
    if report is not None:
        try:_save(report,receipt)
        except BaseException:receipt['passed']=False;receipt['errorCode']=3
    sys.stdout.write(json.dumps(receipt,separators=(',',':'),sort_keys=True)+'\n')
    return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
