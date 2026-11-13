"""Producer-shaped wire4 receipts for portable public-pipeline regressions."""
import copy
import test_ime_mode_receipts as old_mode


def profile_context(binding, setup_deadline):
    """Only the native profile slice; full semantic replay has its own fixtures."""
    from test_writer_model_reader import profile_directory_fixture
    directory=profile_directory_fixture()
    return dict(success=True,phase='post',expectedNative=copy.deepcopy(binding),setupDeadline=setup_deadline,
        observation=dict(bindingBefore=copy.deepcopy(binding),nativeSnapshots=dict(controllerBefore=dict(
            profileUrl=directory['witness']['profileUrl'],profileDirectory=directory))))


def full_post_semantic_context(testcase, binding, setup_deadline, *, focus=43, tid=303):
    """Run the existing PRE/prefix/POST producers with inert API/reader doubles."""
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import patch
    import ascii_editor_input as keyboard
    from ascii_observer_boundary import AsciiObserverBoundary
    from test_ascii_editor_input import FakeWindows
    from test_ime_semantic_context import SemanticSetupTests
    from test_writer_model_barrier import synthetic_frame, original_shell_fixture
    f=SemanticSetupTests();f.setUp();testcase.addCleanup(f.doCleanups)
    f.frame=synthetic_frame(Path(binding['expectedImage']).parents[2],'unused')
    f.frame.binding.update(binding);f.native=copy.deepcopy(binding)
    f.shell=original_shell_fixture(f.frame.binding,f.frame.suite)
    f.now=max(.5,setup_deadline-59.5)
    f.fixture('writer')
    pre,record=f.run_phase(deadline=setup_deadline,
        cleanup=f.clean('writer',deadline=min(setup_deadline,f.now+12),at=f.now+1.5))
    f.now+=.1
    class Windows(FakeWindows):
        def __init__(self):
            super().__init__();self.focus=focus
            self.user.GetWindowThreadProcessId=lambda hwnd,pointer:tid
            self.user.GetForegroundWindow=lambda:binding['suiteHwnd']
            self.user.GetAncestor=lambda hwnd,kind:binding['suiteHwnd']
        def pid(self,hwnd):return binding['shellPid'] if hwnd==binding['suiteHwnd'] else binding['officePid']
        def require_foreground(self,hwnd):assert hwnd==binding['suiteHwnd']
        def editor_focus_snapshot(self,*args):
            row=super().editor_focus_snapshot(*args);row['queriedThreadId']=tid
            for side in ('before','after'):
                for item in row[side].values():
                    if type(item) is dict:item['threadId']=tid
            row['focus']['threadId']=tid
            return row
    with patch.object(keyboard,'_observer',side_effect=AsciiObserverBoundary),patch.object(keyboard.time,'sleep',side_effect=lambda seconds:setattr(f,'now',f.now+seconds)):
        keyboard.type_ascii(Windows(),binding['suiteHwnd'],binding['childHwnd'],f.api.PREFIXES['writer'],record,
            pause=.04,deadline=setup_deadline,clock=lambda:f.now,
            original_popen=SimpleNamespace(pid=binding['shellPid'],_handle=f.shell['handleValue']),
            native_binding=f.native,prepared_library={'testOnlyObserverBoundary':True})
    record.update(asciiPrefix=f.api.PREFIXES['writer'],prefixInputLayout=keyboard.US_LAYOUT,
        windowHwnd=binding['suiteHwnd'],childHwnd=binding['childHwnd'],keyboardFocusHwnd=focus,editorTid=tid)
    f.now+=.1
    post,record=f.run_phase(phase='post',record=record,deadline=setup_deadline,
        cleanup=f.clean('writer',deadline=min(setup_deadline,f.now+12),at=f.now+1.5))
    metadata=dict(expectedNative=copy.deepcopy(binding),setupFinishedAt=post['finishedAt']+.02,
        semanticReadiness=[dict(phase=phase,readerFinishedAt=context['finishedAt'],readerDeadline=context['readerDeadline'],
            setupDeadline=setup_deadline,acknowledgedAt=context['finishedAt']+.01) for phase,context in (('pre',pre),('post',post))])
    return post,metadata


def complete_record(record, *, empty=False, returned=None):
    context=dict(magic=0x4f47494d,version=4,pid=record['officePid'],tid=record['editorTid'],
        targetHwnd=record['keyboardFocusHwnd'],rootHwnd=record['windowHwnd'])
    profile_keys=('layout','previousLayout','previousProfileType','previousLanguage','previousClsid','previousProfile',
        'previousProfileLayout','activeProfileType','activeLanguage','activeClsid','activeProfile','activeProfileLayout',
        'profileManagerHresult','previousProfileHresult','activateProfileHresult','activeProfileHresult','activateLayoutError')
    original_profile={key:copy.deepcopy(record['restoration'][key]) for key in profile_keys}
    profile=record['readiness']['profile'];commands=[]
    original_pair=((1,0,None),(1,0,None)) if empty else ((0,3,1),(0,3,33))
    returned=original_pair if returned is None else returned
    def tags(pair):
        result={}
        for name,(hr,kind,value) in zip(('open','conversion'),pair):
            result[name]=dict(hresult=hr,variantType=kind,kind='i4' if kind==3 else 'empty')
            if kind==3:result[name]['value']=value
        return result
    for sequence in (1,2,3,4):
        r=old_mode.ThreadModeReceiptTests().receipt(sequence)
        if sequence==1:r.update(beforeConversion=33)
        if empty and sequence in (1,2,4):
            if sequence==4:r=old_mode.ThreadModeReceiptTests().receipt(1)
            pair=returned if sequence==4 else original_pair
            for name,(hr,kind,value) in zip(('Open','Conversion'),pair):
                r.update({f'before{name}Hr':hr,f'before{name}Type':kind,f'before{name}':value if kind==3 else 0})
            if sequence==2:r.update(requestedConversion=0,afterConversion=0)
        if empty and sequence==3:r.update(beforeConversion=0,requestedConversion=1,afterConversion=1)
        observed=original_pair if sequence==1 else returned if sequence==4 else ((0,3,1),(0,3,0 if empty and sequence==2 else 1 if empty else 32 if sequence==2 else 33))
        row=dict(original_profile,command=sequence,policyVersion=4,nativeContext=dict(context),startedAt=1.+sequence/10,
            status=0,nativeAck=sequence,publishedCommand=sequence,nativeAttemptedMask=(1<<sequence)-1,
            acknowledged=True,success=True,nativeCallAttempts=1,nativePublicationReturn=1,
            snapshotEvidence=dict(copyReturn=1,ackBefore=sequence,ackAfter=sequence,stable=True),
            commandRejection=dict(count=0,sequence=0,during=0,reason=0),
            deadline=6.+sequence/10,requestedBudget=dict(counter=100000+sequence,frequency=1000),
            modeDeadlineCounter=100000+sequence,modeCounterFrequency=1000,threadMode=r,
            tsfModeCaptured=1,profileChangeAttempted=1,previousTsfOpen=0 if empty else 1,previousTsfConversion=0 if empty else 33,
            typedValues=tags(observed),tsfOrigin='empty' if empty else 'i4',previousImmState=dict(open=0,conversion=1,sentence=8),
            immState=dict(contextPresent=1,conversionSucceeded=1,open=0 if sequence in (1,4) else 1,
                conversion=1 if sequence in (1,4) else 0 if empty and sequence==2 else 1 if empty else 32 if sequence==2 else 33,sentence=8))
        if sequence!=4:row.update(layout=0x04120412,activeLanguage=0x0412,activeProfileType=1,activeClsid=profile['providerClsid'],activeProfile=profile['profileGuid'],activeProfileLayout=0)
        else:row.update(profileHklRestored=True,immEqual=True,typedStateEqual=returned==original_pair,
            restorationDisposition='empty-origin-retirement-required' if empty else 'concrete-restored')
        commands.append(row)
    record.update(imePolicyVersion=4,case='ime-'+record['module'],imeCommands=commands,activeProfile=commands[0],restoration=commands[-1])
    return record
