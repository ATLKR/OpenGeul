use super::{Admission, Bootstrap, JobHeader, PeerIdentity, FIXED_CLSID, MAX_HEADER};
use std::io::Write;
use std::os::windows::{ffi::OsStringExt, process::ExitStatusExt};
use std::{
    ffi::c_void,
    io, mem,
    path::Path,
    ptr,
    sync::{mpsc, Arc, OnceLock},
    thread,
    time::{Duration, Instant},
};
use windows::core::{implement, IUnknown, Interface, Ref, GUID, PCWSTR, PWSTR};
use windows::Win32::{
    Foundation::*,
    Security::Authorization::*,
    Security::*,
    Storage::FileSystem::*,
    Storage::Packaging::Appx::*,
    System::{
        Com::*, Console::*, Environment::*, JobObjects::*, Pipes::*, Registry::*, Rpc::*,
        SystemInformation::*, Threading::*, Variant::*, IO::*,
    },
};

const BOOTSTRAP_SECONDS: u64 = 65;
const PID_DISPID: i32 = 1;
const BEGIN_DISPID: i32 = 2;
const VERSION_DISPID: i32 = 3;
fn fail(message: &'static str) -> io::Error {
    io::Error::other(message)
}
fn win(error: windows::core::Error) -> io::Error {
    if error.code().0 as u32 & 0xffff0000 == 0x80070000 {
        return io::Error::from_raw_os_error(error.code().0 & 0xffff);
    }
    io::Error::other(format!(
        "Windows 작업자 오류 (0x{:08x})",
        error.code().0 as u32
    ))
}
fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(Some(0)).collect()
}
fn guid(value: &str) -> io::Result<GUID> {
    if !super::wire::guid(value) {
        return Err(fail("작업자 클래스 식별자가 올바르지 않습니다."));
    }
    unsafe { CLSIDFromString(PCWSTR(wide(&format!("{{{value}}}")).as_ptr())).map_err(win) }
}
fn fresh_guid() -> io::Result<String> {
    let value = unsafe { CoCreateGuid().map_err(win)? };
    Ok(format!(
        "{:08x}-{:04x}-{:04x}-{:02x}{:02x}-{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
        value.data1,
        value.data2,
        value.data3,
        value.data4[0],
        value.data4[1],
        value.data4[2],
        value.data4[3],
        value.data4[4],
        value.data4[5],
        value.data4[6],
        value.data4[7]
    ))
}
struct Handle(HANDLE);
unsafe impl Send for Handle {}
unsafe impl Sync for Handle {}
impl Handle {
    fn new(value: HANDLE) -> io::Result<Self> {
        if value.is_invalid() {
            Err(io::Error::last_os_error())
        } else {
            Ok(Self(value))
        }
    }
}
impl Drop for Handle {
    fn drop(&mut self) {
        unsafe {
            let _ = CloseHandle(self.0);
        }
    }
}

struct Apartment;
static SECURITY: OnceLock<Result<(), i32>> = OnceLock::new();
impl Apartment {
    fn enter() -> io::Result<Self> {
        unsafe {
            CoInitializeEx(None, COINIT_MULTITHREADED)
                .ok()
                .map_err(win)?;
        }
        let result = SECURITY.get_or_init(|| unsafe {
            CoInitializeSecurity(
                None,
                -1,
                None,
                None,
                RPC_C_AUTHN_LEVEL_PKT_PRIVACY,
                RPC_C_IMP_LEVEL_IDENTIFY,
                None,
                EOLE_AUTHENTICATION_CAPABILITIES(EOAC_DISABLE_AAA.0 | EOAC_NO_CUSTOM_MARSHAL.0),
                None,
            )
            .map_err(|e| e.code().0)
        });
        if let Err(code) = result {
            unsafe {
                CoUninitialize();
            }
            return Err(win(windows::core::Error::from_hresult(
                windows::core::HRESULT(*code),
            )));
        }
        Ok(Self)
    }
}
impl Drop for Apartment {
    fn drop(&mut self) {
        unsafe {
            CoUninitialize();
        }
    }
}

struct State {
    admission: Admission,
    sender: mpsc::Sender<Bootstrap>,
}
#[implement(IDispatch)]
struct Worker {
    state: Arc<State>,
}
impl IDispatch_Impl for Worker_Impl {
    fn GetTypeInfoCount(&self) -> windows::core::Result<u32> {
        Ok(0)
    }
    fn GetTypeInfo(&self, _: u32, _: u32) -> windows::core::Result<ITypeInfo> {
        Err(E_NOTIMPL.into())
    }
    fn GetIDsOfNames(
        &self,
        riid: *const GUID,
        names: *const PCWSTR,
        count: u32,
        _: u32,
        ids: *mut i32,
    ) -> windows::core::Result<()> {
        if riid.is_null()
            || names.is_null()
            || ids.is_null()
            || count != 1
            || unsafe { *riid } != GUID::zeroed()
        {
            return Err(E_INVALIDARG.into());
        }
        let name = unsafe { (*names).to_string() }?;
        let id = match name.as_str() {
            "Pid" => PID_DISPID,
            "Begin" => BEGIN_DISPID,
            "ProtocolVersion" => VERSION_DISPID,
            _ => return Err(DISP_E_UNKNOWNNAME.into()),
        };
        unsafe {
            *ids = id;
        }
        Ok(())
    }
    fn Invoke(
        &self,
        id: i32,
        riid: *const GUID,
        _: u32,
        flags: DISPATCH_FLAGS,
        params: *const DISPPARAMS,
        result: *mut VARIANT,
        _: *mut EXCEPINFO,
        _: *mut u32,
    ) -> windows::core::Result<()> {
        if riid.is_null() || params.is_null() || unsafe { *riid } != GUID::zeroed() {
            return Err(E_INVALIDARG.into());
        }
        let params = unsafe { &*params };
        if params.cNamedArgs != 0 {
            return Err(DISP_E_NONAMEDARGS.into());
        }
        if matches!(id, PID_DISPID | VERSION_DISPID)
            && flags == DISPATCH_PROPERTYGET
            && params.cArgs == 0
            && !result.is_null()
        {
            unsafe {
                *result = VARIANT::from(if id == PID_DISPID {
                    GetCurrentProcessId()
                } else {
                    1
                });
            }
            return Ok(());
        }
        if id != BEGIN_DISPID
            || flags != DISPATCH_METHOD
            || params.cArgs != 1
            || params.rgvarg.is_null()
        {
            return Err(DISP_E_MEMBERNOTFOUND.into());
        }
        verify_com_caller().map_err(|_| windows::core::Error::from(E_ACCESSDENIED))?;
        let arg = unsafe { &*params.rgvarg };
        // 타입 강제변환은 하지 않는다. Automation primitive BSTR 한 개만 허용한다.
        if unsafe { arg.Anonymous.Anonymous.vt } != VT_BSTR {
            return Err(DISP_E_TYPEMISMATCH.into());
        }
        let text = unsafe { &arg.Anonymous.Anonymous.Anonymous.bstrVal };
        if text.len() > 4096 {
            return Err(E_INVALIDARG.into());
        }
        let text =
            String::from_utf16(text).map_err(|_| windows::core::Error::from(E_INVALIDARG))?;
        let metadata = self
            .state
            .admission
            .admit(&text, unsafe { GetCurrentProcessId() })
            .map_err(|_| windows::core::Error::from(E_ACCESSDENIED))?;
        self.state
            .sender
            .send(metadata)
            .map_err(|_| windows::core::Error::from(E_FAIL))?;
        // 이 응답 후에만 부모가 header를 쓴다. 원 CLI는 header를 읽기 전까지 실행하지 않는다.
        Ok(())
    }
}
#[implement(IClassFactory)]
struct Factory {
    state: Arc<State>,
}
impl IClassFactory_Impl for Factory_Impl {
    fn CreateInstance(
        &self,
        outer: Ref<'_, IUnknown>,
        iid: *const GUID,
        out: *mut *mut c_void,
    ) -> windows::core::Result<()> {
        if !outer.is_null() {
            return Err(CLASS_E_NOAGGREGATION.into());
        }
        if iid.is_null() || out.is_null() {
            return Err(E_POINTER.into());
        }
        let worker: IDispatch = Worker {
            state: self.state.clone(),
        }
        .into();
        unsafe { worker.query(iid, out).ok() }
    }
    fn LockServer(&self, lock: windows::core::BOOL) -> windows::core::Result<()> {
        if lock.as_bool() {
            Err(E_NOTIMPL.into())
        } else {
            Ok(())
        }
    }
}
struct Class(u32);
impl Drop for Class {
    fn drop(&mut self) {
        unsafe {
            let _ = CoRevokeClassObject(self.0);
        }
    }
}
fn invoke(
    object: &IDispatch,
    id: i32,
    flags: DISPATCH_FLAGS,
    arg: Option<&str>,
) -> io::Result<VARIANT> {
    let mut value = arg.map(VARIANT::from);
    let params = DISPPARAMS {
        rgvarg: value.as_mut().map_or(ptr::null_mut(), |v| v as *mut _),
        rgdispidNamedArgs: ptr::null_mut(),
        cArgs: if value.is_some() { 1 } else { 0 },
        cNamedArgs: 0,
    };
    let mut result = VARIANT::default();
    unsafe {
        object
            .Invoke(
                id,
                &GUID::zeroed(),
                0,
                flags,
                &params,
                Some(&mut result),
                None,
                None,
            )
            .map_err(win)?;
    }
    Ok(result)
}

fn token_buffer(process: HANDLE, class: TOKEN_INFORMATION_CLASS) -> io::Result<Vec<usize>> {
    let mut token = HANDLE::default();
    unsafe {
        OpenProcessToken(process, TOKEN_QUERY, &mut token).map_err(win)?;
    }
    let token = Handle::new(token)?;
    query_token(token.0, class)
}
fn query_token(token: HANDLE, class: TOKEN_INFORMATION_CLASS) -> io::Result<Vec<usize>> {
    let mut length = 0;
    unsafe {
        let _ = GetTokenInformation(token, class, None, 0, &mut length);
    }
    if length == 0 || length > 65536 {
        return Err(fail("작업자 사용자 정보를 확인하지 못했습니다."));
    }
    let mut buffer =
        vec![0usize; (length as usize + mem::size_of::<usize>() - 1) / mem::size_of::<usize>()];
    unsafe {
        GetTokenInformation(
            token,
            class,
            Some(buffer.as_mut_ptr().cast()),
            length,
            &mut length,
        )
        .map_err(win)?;
    }
    Ok(buffer)
}
fn logon_sid(process: HANDLE) -> io::Result<String> {
    let buffer = token_buffer(process, TokenLogonSid)?;
    let groups = unsafe { &*(buffer.as_ptr().cast::<TOKEN_GROUPS>()) };
    if groups.GroupCount != 1 {
        return Err(fail("작업자 로그온 정보를 확인하지 못했습니다."));
    }
    sid_text(groups.Groups[0].Sid)
}
fn sid_text(sid: PSID) -> io::Result<String> {
    let mut text = PWSTR::null();
    unsafe {
        ConvertSidToStringSidW(sid, &mut text).map_err(win)?;
    }
    let result =
        unsafe { text.to_string() }.map_err(|_| fail("작업자 SID 문자열이 올바르지 않습니다."));
    unsafe {
        let _ = LocalFree(Some(HLOCAL(text.0.cast())));
    }
    result
}
fn identity(token: HANDLE) -> io::Result<PeerIdentity> {
    let user = query_token(token, TokenUser)?;
    let user = sid_text(unsafe { (*(user.as_ptr().cast::<TOKEN_USER>())).User.Sid })?;
    let logon = query_token(token, TokenLogonSid)?;
    let groups = unsafe { &*(logon.as_ptr().cast::<TOKEN_GROUPS>()) };
    if groups.GroupCount != 1 {
        return Err(fail("작업자 로그온 토큰이 올바르지 않습니다."));
    }
    let logon = sid_text(groups.Groups[0].Sid)?;
    let integrity = query_token(token, TokenIntegrityLevel)?;
    let sid = unsafe {
        (*(integrity.as_ptr().cast::<TOKEN_MANDATORY_LABEL>()))
            .Label
            .Sid
    };
    let count = unsafe { *GetSidSubAuthorityCount(sid) };
    if count == 0 {
        return Err(fail("작업자 무결성 토큰이 올바르지 않습니다."));
    }
    let integrity = unsafe { *GetSidSubAuthority(sid, count as u32 - 1) };
    let elevation = query_token(token, TokenElevation)?;
    let elevated =
        unsafe { (*(elevation.as_ptr().cast::<TOKEN_ELEVATION>())).TokenIsElevated != 0 };
    Ok(PeerIdentity {
        user,
        logon,
        integrity,
        elevated,
    })
}
fn process_identity(process: HANDLE) -> io::Result<PeerIdentity> {
    let mut token = HANDLE::default();
    unsafe {
        OpenProcessToken(process, TOKEN_QUERY, &mut token).map_err(win)?;
    }
    let token = Handle::new(token)?;
    identity(token.0)
}
fn verify_com_caller() -> io::Result<()> {
    let own = process_identity(unsafe { GetCurrentProcess() })?;
    unsafe {
        CoImpersonateClient().map_err(win)?;
    }
    struct Revert;
    impl Drop for Revert {
        fn drop(&mut self) {
            unsafe {
                let _ = CoRevertToSelf();
            }
        }
    }
    let _revert = Revert;
    let mut token = HANDLE::default();
    unsafe {
        OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, true, &mut token).map_err(win)?;
    }
    let token = Handle::new(token)?;
    if !own.matches(&identity(token.0)?) {
        return Err(fail("호출자의 로그온·무결성·권한이 작업자와 다릅니다."));
    }
    Ok(())
}
fn elevated() -> io::Result<bool> {
    let buffer = token_buffer(unsafe { GetCurrentProcess() }, TokenElevation)?;
    Ok(unsafe { (*(buffer.as_ptr().cast::<TOKEN_ELEVATION>())).TokenIsElevated != 0 })
}
fn image(process: HANDLE) -> io::Result<std::path::PathBuf> {
    let mut value = vec![0u16; 32768];
    let mut length = value.len() as u32;
    unsafe {
        QueryFullProcessImageNameW(
            process,
            PROCESS_NAME_WIN32,
            PWSTR(value.as_mut_ptr()),
            &mut length,
        )
        .map_err(win)?;
    }
    Ok(std::path::PathBuf::from(std::ffi::OsString::from_wide(
        &value[..length as usize],
    )))
}
fn own_process(pid: u32, terminate: bool) -> io::Result<Handle> {
    if pid == 0 || (terminate && pid == unsafe { GetCurrentProcessId() }) {
        return Err(fail("작업자 PID가 올바르지 않습니다."));
    }
    let access = PROCESS_QUERY_LIMITED_INFORMATION
        | PROCESS_ACCESS_RIGHTS(0x00100000)
        | if terminate {
            PROCESS_TERMINATE | PROCESS_SET_QUOTA
        } else {
            PROCESS_ACCESS_RIGHTS(0)
        };
    let handle = unsafe { OpenProcess(access, false, pid).map_err(win)? };
    let handle = Handle::new(handle)?;
    let current = unsafe { GetCurrentProcess() };
    if std::fs::canonicalize(image(handle.0)?)? != std::fs::canonicalize(std::env::current_exe()?)?
        || !process_identity(handle.0)?.matches(&process_identity(current)?)
    {
        return Err(fail("소유한 문서 작업자 프로세스가 아닙니다."));
    }
    let mut peer = IMAGE_FILE_MACHINE::default();
    let mut peer_native = IMAGE_FILE_MACHINE::default();
    let mut own = IMAGE_FILE_MACHINE::default();
    let mut own_native = IMAGE_FILE_MACHINE::default();
    unsafe {
        IsWow64Process2(handle.0, &mut peer, Some(&mut peer_native)).map_err(win)?;
        IsWow64Process2(current, &mut own, Some(&mut own_native)).map_err(win)?;
    }
    if peer != own || peer_native != own_native {
        return Err(fail("작업자 아키텍처가 현재 CLI와 다릅니다."));
    }
    Ok(handle)
}

struct Pipe {
    handle: Handle,
}
impl Pipe {
    fn create(name: &str, output: bool, sid: &str, integrity: u32) -> io::Result<Self> {
        // 같은 로그온의 read/write만 허용하고 pipe instance 생성 권한(0x4)은 주지 않는다.
        let sddl = wide(&format!(
            "D:P(A;;0x100003;;;{sid})S:(ML;;NWNR;;;S-1-16-{integrity})"
        ));
        let mut descriptor = PSECURITY_DESCRIPTOR::default();
        unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                PCWSTR(sddl.as_ptr()),
                SDDL_REVISION_1,
                &mut descriptor,
                None,
            )
            .map_err(win)?;
        }
        let security = SECURITY_ATTRIBUTES {
            nLength: mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: descriptor.0,
            bInheritHandle: windows::core::BOOL(0),
        };
        let handle = unsafe {
            CreateNamedPipeW(
                PCWSTR(wide(name).as_ptr()),
                (if output {
                    PIPE_ACCESS_OUTBOUND
                } else {
                    PIPE_ACCESS_INBOUND
                }) | FILE_FLAG_FIRST_PIPE_INSTANCE
                    | FILE_FLAG_OVERLAPPED,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1,
                65536,
                65536,
                0,
                Some(&security),
            )
        };
        let error = io::Error::last_os_error();
        unsafe {
            let _ = LocalFree(Some(HLOCAL(descriptor.0)));
        }
        if handle.is_invalid() {
            return Err(error);
        }
        Ok(Self {
            handle: Handle(handle),
        })
    }
    fn connect(&self, pid: u32, deadline: Instant) -> io::Result<()> {
        self.operation(
            Some(deadline),
            |ov, _| unsafe { ConnectNamedPipe(self.handle.0, Some(ov)) },
            true,
        )?;
        let mut peer = 0;
        unsafe {
            GetNamedPipeClientProcessId(self.handle.0, &mut peer).map_err(win)?;
        }
        if peer != pid {
            return Err(fail("문서 작업자 pipe의 소유 프로세스가 다릅니다."));
        }
        Ok(())
    }
    fn operation<F>(&self, deadline: Option<Instant>, start: F, connection: bool) -> io::Result<u32>
    where
        F: FnOnce(*mut OVERLAPPED, *mut u32) -> windows::core::Result<()>,
    {
        let event = Handle::new(unsafe { CreateEventW(None, true, false, None).map_err(win)? })?;
        let mut ov = OVERLAPPED {
            hEvent: event.0,
            ..Default::default()
        };
        let mut count = 0;
        match start(&mut ov, &mut count) {
            Ok(()) => return Ok(count),
            Err(e)
                if connection
                    && e.code() == windows::core::HRESULT::from_win32(ERROR_PIPE_CONNECTED.0) =>
            {
                return Ok(0)
            }
            Err(e) if e.code() == windows::core::HRESULT::from_win32(ERROR_IO_PENDING.0) => {}
            Err(e) => return Err(win(e)),
        }
        let timeout = deadline.map_or(INFINITE, |d| {
            d.saturating_duration_since(Instant::now())
                .as_millis()
                .min(u32::MAX as u128 - 1) as u32
        });
        let wait = unsafe { WaitForSingleObject(event.0, timeout) };
        if wait != WAIT_OBJECT_0 {
            // OVERLAPPED와 buffer가 살아 있는 동안 cancellation 완료까지 회수한다.
            unsafe {
                let _ = CancelIoEx(self.handle.0, Some(&ov));
                let _ = GetOverlappedResult(self.handle.0, &ov, &mut count, true);
            }
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "문서 작업자 연결 시간이 초과되었습니다.",
            ));
        }
        unsafe {
            GetOverlappedResult(self.handle.0, &ov, &mut count, false).map_err(win)?;
        }
        Ok(count)
    }
    fn write_all(&self, mut data: &[u8], deadline: Option<Instant>) -> io::Result<()> {
        while !data.is_empty() {
            let size = data.len().min(65536);
            let count = self.operation(
                deadline,
                |ov, count| unsafe {
                    WriteFile(self.handle.0, Some(&data[..size]), Some(count), Some(ov))
                },
                false,
            )? as usize;
            if count == 0 {
                return Err(io::Error::new(
                    io::ErrorKind::WriteZero,
                    "문서 작업자 입력을 전달하지 못했습니다.",
                ));
            }
            data = &data[count..];
        }
        Ok(())
    }
    fn read_all(&self) -> io::Result<Vec<u8>> {
        let mut result = Vec::new();
        let mut buffer = vec![0u8; 65536];
        loop {
            let count = self.operation(
                None,
                |ov, count| unsafe {
                    ReadFile(self.handle.0, Some(&mut buffer), Some(count), Some(ov))
                },
                false,
            );
            match count {
                Ok(0) => break,
                Ok(n) => result.extend_from_slice(&buffer[..n as usize]),
                Err(e) if matches!(e.raw_os_error(), Some(109 | 232)) => break,
                Err(e) => return Err(e),
            }
        }
        Ok(result)
    }
    fn read_exact(&self, mut data: &mut [u8], deadline: Instant) -> io::Result<()> {
        while !data.is_empty() {
            let count = self.operation(
                Some(deadline),
                |ov, count| unsafe { ReadFile(self.handle.0, Some(data), Some(count), Some(ov)) },
                false,
            )? as usize;
            if count == 0 {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "작업자 인증 응답이 끝났습니다.",
                ));
            }
            data = &mut data[count..];
        }
        Ok(())
    }
}

struct OwnedWorker {
    process: Handle,
    _job: Handle,
    completed: bool,
}
impl OwnedWorker {
    fn attach(process: Handle) -> io::Result<Self> {
        let job = Handle::new(unsafe { CreateJobObjectW(None, None).map_err(win)? })?;
        let result = Self {
            process,
            _job: job,
            completed: false,
        };
        let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        unsafe {
            SetInformationJobObject(
                result._job.0,
                JobObjectExtendedLimitInformation,
                (&info as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                mem::size_of_val(&info) as u32,
            )
            .map_err(win)?;
            AssignProcessToJobObject(result._job.0, result.process.0).map_err(win)?;
        }
        Ok(result)
    }
    fn wait(&mut self) -> io::Result<std::process::ExitStatus> {
        if unsafe { WaitForSingleObject(self.process.0, INFINITE) } != WAIT_OBJECT_0 {
            return Err(io::Error::last_os_error());
        }
        let mut code = 0;
        unsafe {
            GetExitCodeProcess(self.process.0, &mut code).map_err(win)?;
        }
        self.completed = true;
        Ok(std::process::ExitStatus::from_raw(code))
    }
}
impl Drop for OwnedWorker {
    fn drop(&mut self) {
        if !self.completed {
            unsafe {
                let _ = TerminateProcess(self.process.0, 1);
                let _ = WaitForSingleObject(self.process.0, 5000);
            }
        }
    }
}

struct Key(HKEY);
impl Drop for Key {
    fn drop(&mut self) {
        unsafe {
            let _ = RegCloseKey(self.0);
        }
    }
}
fn reg_result(code: WIN32_ERROR) -> io::Result<()> {
    if code == ERROR_SUCCESS {
        Ok(())
    } else {
        Err(io::Error::from_raw_os_error(code.0 as i32))
    }
}
fn open_key(root: HKEY, path: &str, access: REG_SAM_FLAGS) -> io::Result<Key> {
    let mut value = HKEY::default();
    reg_result(unsafe {
        RegOpenKeyExW(
            root,
            PCWSTR(wide(path).as_ptr()),
            None,
            access | KEY_WOW64_64KEY,
            &mut value,
        )
    })?;
    Ok(Key(value))
}
fn reg_set(key: HKEY, name: &str, value: &str) -> io::Result<()> {
    let value = wide(value);
    let bytes = unsafe { std::slice::from_raw_parts(value.as_ptr().cast::<u8>(), value.len() * 2) };
    reg_result(unsafe {
        RegSetValueExW(key, PCWSTR(wide(name).as_ptr()), None, REG_SZ, Some(bytes))
    })
}
fn reg_get(key: HKEY, name: &str) -> io::Result<String> {
    let mut kind = REG_VALUE_TYPE::default();
    let mut length = 0;
    reg_result(unsafe {
        RegQueryValueExW(
            key,
            PCWSTR(wide(name).as_ptr()),
            None,
            Some(&mut kind),
            None,
            Some(&mut length),
        )
    })?;
    if kind != REG_SZ || length == 0 || length > 65536 || length % 2 != 0 {
        return Err(fail("작업자 등록 값이 올바르지 않습니다."));
    }
    let mut buffer = vec![0u16; length as usize / 2];
    reg_result(unsafe {
        RegQueryValueExW(
            key,
            PCWSTR(wide(name).as_ptr()),
            None,
            Some(&mut kind),
            Some(buffer.as_mut_ptr().cast()),
            Some(&mut length),
        )
    })?;
    if kind != REG_SZ || buffer.last() != Some(&0) {
        return Err(fail("작업자 등록 값이 변경되었습니다."));
    }
    String::from_utf16(&buffer[..buffer.len() - 1])
        .map_err(|_| fail("작업자 등록 값이 올바르지 않습니다."))
}
fn key_shape(key: HKEY, subkeys: u32, values: u32) -> io::Result<bool> {
    let mut actual_subkeys = 0;
    let mut actual_values = 0;
    reg_result(unsafe {
        RegQueryInfoKeyW(
            key,
            None,
            None,
            None,
            Some(&mut actual_subkeys),
            None,
            None,
            Some(&mut actual_values),
            None,
            None,
            None,
            None,
        )
    })?;
    Ok(actual_subkeys == subkeys && actual_values == values)
}
fn created(process: HANDLE) -> io::Result<u64> {
    let mut birth = FILETIME::default();
    let mut exit = FILETIME::default();
    let mut kernel = FILETIME::default();
    let mut user = FILETIME::default();
    unsafe {
        GetProcessTimes(process, &mut birth, &mut exit, &mut kernel, &mut user).map_err(win)?;
    }
    Ok(((birth.dwHighDateTime as u64) << 32) | birth.dwLowDateTime as u64)
}
fn reg_optional(key: HKEY, name: &str) -> io::Result<Option<String>> {
    match reg_get(key, name) {
        Ok(value) => Ok(Some(value)),
        Err(e) if e.raw_os_error() == Some(2) => Ok(None),
        Err(e) => Err(e),
    }
}
struct Registration {
    root: HKEY,
    path: String,
    owner: String,
    command: String,
    exe: String,
    active: bool,
    complete: bool,
    parent: Option<Handle>,
    parent_pid: u32,
}
impl Registration {
    fn create(clsid: &str, exe: &Path) -> io::Result<Self> {
        if !super::wire::guid(clsid) || clsid == FIXED_CLSID {
            return Err(fail(
                "임시 등록에는 새 portable 클래스만 사용할 수 있습니다.",
            ));
        }
        // 형식·image·생성 시간을 모두 확인한 뒤에만 새 key를 만든다.
        let exe = exe
            .to_str()
            .ok_or_else(|| fail("작업자 실행 파일 경로를 표현할 수 없습니다."))?
            .to_string();
        let command = format!("\"{exe}\" --opengeul-com-worker --clsid {clsid}");
        let parent_pid = unsafe { GetCurrentProcessId() };
        let owner = format!(
            "OpenGeul-v1:{clsid}:{parent_pid}:{}",
            created(unsafe { GetCurrentProcess() })?
        );
        let path = format!("Software\\Classes\\CLSID\\{{{clsid}}}");
        let merged = format!("CLSID\\{{{clsid}}}");
        match open_key(HKEY_CLASSES_ROOT, &merged, KEY_READ) {
            Ok(_) => return Err(fail("기존 COM 작업자 등록은 덮어쓰지 않습니다.")),
            Err(e) if e.raw_os_error() == Some(ERROR_FILE_NOT_FOUND.0 as i32) => {}
            Err(e) => return Err(e),
        }
        let root = if elevated()? {
            HKEY_LOCAL_MACHINE
        } else {
            HKEY_CURRENT_USER
        };
        let mut key = HKEY::default();
        let mut disposition = REG_CREATE_KEY_DISPOSITION::default();
        reg_result(unsafe {
            RegCreateKeyExW(
                root,
                PCWSTR(wide(&path).as_ptr()),
                None,
                None,
                REG_OPTION_NON_VOLATILE,
                KEY_READ | KEY_WRITE | KEY_WOW64_64KEY,
                None,
                &mut key,
                Some(&mut disposition),
            )
        })?;
        let key = Key(key);
        if disposition != REG_CREATED_NEW_KEY {
            return Err(fail("기존 COM 작업자 등록은 덮어쓰지 않습니다."));
        }
        let mut result = Self {
            root,
            path,
            owner,
            command,
            exe,
            active: true,
            complete: false,
            parent: None,
            parent_pid,
        };
        // 등록 생성에 성공한 exact key만 소유한다. 기존 key는 위에서 수정 전에 거부한다.
        if let Err(error) = reg_set(key.0, "OpenGeulOwner", &result.owner) {
            // 소유 marker 기록 자체가 실패하면, 우리가 새로 만든 빈 key만 회수한다.
            result.active = false;
            if key_shape(key.0, 0, 0).unwrap_or(false) {
                let _ = reg_result(unsafe {
                    RegDeleteKeyExW(
                        root,
                        PCWSTR(wide(&result.path).as_ptr()),
                        KEY_WOW64_64KEY.0,
                        None,
                    )
                });
            }
            return Err(error);
        }
        let mut server = HKEY::default();
        let mut server_disposition = REG_CREATE_KEY_DISPOSITION::default();
        reg_result(unsafe {
            RegCreateKeyExW(
                key.0,
                PCWSTR(wide("LocalServer32").as_ptr()),
                None,
                None,
                REG_OPTION_NON_VOLATILE,
                KEY_READ | KEY_WRITE,
                None,
                &mut server,
                Some(&mut server_disposition),
            )
        })?;
        let server = Key(server);
        if server_disposition != REG_CREATED_NEW_KEY {
            return Err(fail("기존 작업자 server 등록은 덮어쓰지 않습니다."));
        }
        reg_set(server.0, "", &result.command)?;
        reg_set(server.0, "ServerExecutable", &result.exe)?;
        result.complete = true;
        Ok(result)
    }
    fn adopt(clsid: &str) -> io::Result<Option<Self>> {
        if clsid == FIXED_CLSID {
            return Ok(None);
        }
        let root = if elevated()? {
            HKEY_LOCAL_MACHINE
        } else {
            HKEY_CURRENT_USER
        };
        let path = format!("Software\\Classes\\CLSID\\{{{clsid}}}");
        let key = open_key(root, &path, KEY_READ)?;
        let owner = reg_get(key.0, "OpenGeulOwner")?;
        let prefix = format!("OpenGeul-v1:{clsid}:");
        let fields: Vec<_> = owner
            .strip_prefix(&prefix)
            .ok_or_else(|| fail("소유한 작업자 등록이 아닙니다."))?
            .split(':')
            .collect();
        if fields.len() != 2 {
            return Err(fail("작업자 등록의 소유 정보가 올바르지 않습니다."));
        }
        let pid = fields[0]
            .parse::<u32>()
            .map_err(|_| fail("작업자 부모 PID가 올바르지 않습니다."))?;
        let birth = fields[1]
            .parse::<u64>()
            .map_err(|_| fail("작업자 부모 생성 시간이 올바르지 않습니다."))?;
        let parent = own_process(pid, false)?;
        if created(parent.0)? != birth {
            return Err(fail("작업자 등록의 부모 프로세스가 바뀌었습니다."));
        }
        let server = open_key(key.0, "LocalServer32", KEY_READ)?;
        let exe = reg_get(server.0, "ServerExecutable")?;
        if std::fs::canonicalize(&exe)? != std::fs::canonicalize(std::env::current_exe()?)? {
            return Err(fail("등록한 작업자 실행 파일이 다릅니다."));
        }
        let command = format!("\"{exe}\" --opengeul-com-worker --clsid {clsid}");
        if !key_shape(key.0, 1, 1)?
            || !key_shape(server.0, 0, 2)?
            || reg_get(server.0, "")? != command
        {
            return Err(fail("작업자 임시 등록이 변경되었습니다."));
        }
        Ok(Some(Self {
            root,
            path,
            owner,
            command,
            exe,
            active: true,
            complete: true,
            parent: Some(parent),
            parent_pid: pid,
        }))
    }
    fn cleanup(&mut self) -> io::Result<()> {
        if !self.active {
            return Ok(());
        }
        let key = match open_key(self.root, &self.path, KEY_READ) {
            Ok(k) => k,
            Err(e) if e.raw_os_error() == Some(ERROR_FILE_NOT_FOUND.0 as i32) => {
                self.active = false;
                return Ok(());
            }
            Err(e) => return Err(e),
        };
        if reg_get(key.0, "OpenGeulOwner")? != self.owner {
            return Err(fail("임시 등록 소유 정보가 변경되어 삭제하지 않았습니다."));
        }
        let server = match open_key(key.0, "LocalServer32", KEY_READ) {
            Ok(value) => Some(value),
            Err(e) if !self.complete && e.raw_os_error() == Some(2) => None,
            Err(e) => return Err(e),
        };
        let safe = if let Some(server) = server.as_ref() {
            let command = reg_optional(server.0, "")?;
            let exe = reg_optional(server.0, "ServerExecutable")?;
            let count = u32::from(command.is_some()) + u32::from(exe.is_some());
            key_shape(key.0, 1, 1)?
                && key_shape(server.0, 0, count)?
                && (!self.complete || count == 2)
                && command
                    .as_ref()
                    .map_or(true, |value| value == &self.command)
                && exe.as_ref().map_or(true, |value| value == &self.exe)
        } else {
            key_shape(key.0, 0, 1)?
        };
        if !safe {
            return Err(fail("임시 작업자 등록이 변경되어 삭제하지 않았습니다."));
        }
        let has_server = server.is_some();
        drop(server);
        drop(key);
        if has_server {
            reg_result(unsafe {
                RegDeleteKeyExW(
                    self.root,
                    PCWSTR(wide(&(self.path.clone() + "\\LocalServer32")).as_ptr()),
                    KEY_WOW64_64KEY.0,
                    None,
                )
            })?;
        }
        reg_result(unsafe {
            RegDeleteKeyExW(
                self.root,
                PCWSTR(wide(&self.path).as_ptr()),
                KEY_WOW64_64KEY.0,
                None,
            )
        })?;
        self.active = false;
        Ok(())
    }
}
impl Drop for Registration {
    fn drop(&mut self) {
        let _ = self.cleanup();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn temporary_registration_collision_preserves_existing_values() {
        let clsid = fresh_guid().unwrap();
        let exe = std::env::current_exe().unwrap();
        let mut owned = Registration::create(&clsid, &exe).unwrap();
        let key = open_key(owned.root, &owned.path, KEY_READ).unwrap();
        assert!(Registration::create(&clsid, &exe).is_err());
        assert_eq!(reg_get(key.0, "OpenGeulOwner").unwrap(), owned.owner);
        let server = open_key(key.0, "LocalServer32", KEY_READ).unwrap();
        assert_eq!(reg_get(server.0, "ServerExecutable").unwrap(), owned.exe);
        drop(server);
        drop(key);
        owned.cleanup().unwrap();
        assert_eq!(
            open_key(owned.root, &owned.path, KEY_READ)
                .err()
                .unwrap()
                .raw_os_error(),
            Some(2)
        );
    }

    #[test]
    fn changed_owner_prevents_deleting_a_registration() {
        let mut owned =
            Registration::create(&fresh_guid().unwrap(), &std::env::current_exe().unwrap())
                .unwrap();
        let key = open_key(owned.root, &owned.path, KEY_READ | KEY_WRITE).unwrap();
        reg_set(key.0, "OpenGeulOwner", "synthetic-foreign-owner").unwrap();
        assert!(owned.cleanup().is_err());
        assert_eq!(
            reg_get(key.0, "OpenGeulOwner").unwrap(),
            "synthetic-foreign-owner"
        );
        // 테스트가 만든 원본 값으로만 복원한 뒤 소유 guard로 회수한다.
        reg_set(key.0, "OpenGeulOwner", &owned.owner).unwrap();
        drop(key);
        owned.cleanup().unwrap();
    }

    #[test]
    fn partial_owned_server_is_cleaned_without_removing_unknown_values() {
        let mut owned =
            Registration::create(&fresh_guid().unwrap(), &std::env::current_exe().unwrap())
                .unwrap();
        let key = open_key(owned.root, &owned.path, KEY_READ | KEY_WRITE).unwrap();
        let server = open_key(key.0, "LocalServer32", KEY_READ | KEY_WRITE).unwrap();
        reg_result(unsafe { RegDeleteValueW(server.0, PCWSTR(wide("ServerExecutable").as_ptr())) })
            .unwrap();
        owned.complete = false;
        reg_set(server.0, "ForeignValue", "preserve").unwrap();
        assert!(owned.cleanup().is_err());
        assert_eq!(reg_get(server.0, "ForeignValue").unwrap(), "preserve");
        reg_result(unsafe { RegDeleteValueW(server.0, PCWSTR(wide("ForeignValue").as_ptr())) })
            .unwrap();
        drop(server);
        drop(key);
        owned.cleanup().unwrap();
        assert_eq!(
            open_key(owned.root, &owned.path, KEY_READ)
                .err()
                .unwrap()
                .raw_os_error(),
            Some(2)
        );
    }

    #[test]
    fn fixed_package_class_is_never_a_temporary_cleanup_target() {
        assert!(Registration::create(FIXED_CLSID, &std::env::current_exe().unwrap()).is_err());
        assert!(Registration::adopt(FIXED_CLSID).unwrap().is_none());
    }

    #[test]
    fn current_parent_pid_cannot_be_attached_as_a_terminable_worker() {
        assert!(own_process(unsafe { GetCurrentProcessId() }, true).is_err());
        assert!(own_process(0, true).is_err());
    }
}
fn packaged() -> io::Result<bool> {
    let mut length = 0;
    let result = unsafe { GetCurrentPackageFullName(&mut length, None) };
    if result == APPMODEL_ERROR_NO_PACKAGE {
        Ok(false)
    } else if result == ERROR_INSUFFICIENT_BUFFER {
        Ok(true)
    } else {
        Err(fail("현재 CLI 패키지 식별자를 확인하지 못했습니다."))
    }
}
fn environment() -> io::Result<Vec<u16>> {
    let raw = unsafe { GetEnvironmentStringsW() };
    if raw.is_null() {
        return Err(io::Error::last_os_error());
    }
    let mut count = 0;
    let result = (|| {
        loop {
            if count >= MAX_HEADER / 2 {
                return Err(fail("작업자 환경 정보가 보호 헤더 상한을 초과합니다."));
            }
            if unsafe { *raw.0.add(count) == 0 && *raw.0.add(count + 1) == 0 } {
                break;
            }
            count += 1;
        }
        Ok(unsafe { std::slice::from_raw_parts(raw.0, count + 2) }.to_vec())
    })();
    unsafe {
        let _ = FreeEnvironmentStringsW(raw);
    }
    result
}
fn cwd() -> io::Result<Vec<u16>> {
    let length = unsafe { GetCurrentDirectoryW(None) };
    if length == 0 || length > 32768 {
        return Err(io::Error::last_os_error());
    }
    let mut value = vec![0u16; length as usize];
    let written = unsafe { GetCurrentDirectoryW(Some(&mut value)) };
    if written == 0 || written >= length {
        return Err(fail("작업자 기준 폴더가 변경되었습니다."));
    }
    value.truncate(written as usize);
    Ok(value)
}

pub fn run_cli(
    exe: &Path,
    args: &[String],
    stdin_payload: Option<&[u8]>,
) -> io::Result<std::process::Output> {
    if std::fs::canonicalize(exe)? != std::fs::canonicalize(std::env::current_exe()?)?
        || args.iter().any(|a| a.contains('\0'))
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "소유한 CLI 실행 파일과 유효한 인수만 사용할 수 있습니다.",
        ));
    }
    let _apartment = Apartment::enter()?;
    let clsid = if packaged()? {
        FIXED_CLSID.into()
    } else {
        fresh_guid()?
    };
    let mut registration = if clsid == FIXED_CLSID {
        None
    } else {
        Some(Registration::create(&clsid, exe)?)
    };
    let object: IDispatch = unsafe {
        CoCreateInstance(
            &guid(&clsid)?,
            None,
            CLSCTX_LOCAL_SERVER | CLSCTX_DISABLE_AAA,
        )
        .map_err(win)?
    };
    unsafe {
        CoSetProxyBlanket(
            &object,
            RPC_C_AUTHN_WINNT,
            RPC_C_AUTHZ_NONE,
            PCWSTR::null(),
            RPC_C_AUTHN_LEVEL_PKT_PRIVACY,
            RPC_C_IMP_LEVEL_IDENTIFY,
            None,
            EOAC_NONE,
        )
        .map_err(win)?;
    }
    let version = invoke(&object, VERSION_DISPID, DISPATCH_PROPERTYGET, None)?;
    let pid = invoke(&object, PID_DISPID, DISPATCH_PROPERTYGET, None)?;
    if unsafe { version.Anonymous.Anonymous.vt } != VT_UI4
        || unsafe { pid.Anonymous.Anonymous.vt } != VT_UI4
        || u32::try_from(&version).map_err(win)? != 1
    {
        return Err(fail("COM 작업자 프로토콜이 일치하지 않습니다."));
    }
    let pid = u32::try_from(&pid).map_err(win)?;
    let process = own_process(pid, true)?;
    let worker_birth = created(process.0)?;
    let metadata = Bootstrap {
        version: 1,
        job: fresh_guid()?,
        nonce: fresh_guid()?.replace('-', ""),
        parent_pid: unsafe { GetCurrentProcessId() },
        worker_pid: pid,
    };
    metadata.validate(pid)?;
    let sid = logon_sid(unsafe { GetCurrentProcess() })?;
    let integrity = process_identity(unsafe { GetCurrentProcess() })?.integrity;
    let input = Pipe::create(&metadata.pipe("stdin")?, true, &sid, integrity)?;
    let output = Pipe::create(&metadata.pipe("stdout")?, false, &sid, integrity)?;
    let error = Pipe::create(&metadata.pipe("stderr")?, false, &sid, integrity)?;
    let mut argv = vec![exe.to_string_lossy().into_owned()];
    argv.extend_from_slice(args);
    let header = JobHeader {
        version: 1,
        nonce: metadata.nonce.clone(),
        parent_pid: metadata.parent_pid,
        worker_pid: pid,
        args: argv,
        cwd: cwd()?,
        environment: environment()?,
    }
    .encode()?;
    let bootstrap = serde_json::to_string(&metadata)
        .map_err(|_| fail("작업자 연결 정보를 만들지 못했습니다."))?;
    invoke(&object, BEGIN_DISPID, DISPATCH_METHOD, Some(&bootstrap))?;
    let deadline = Instant::now() + Duration::from_secs(BOOTSTRAP_SECONDS);
    input.connect(pid, deadline)?;
    output.connect(pid, deadline)?;
    error.connect(pid, deadline)?;
    // PID property는 아직 신뢰하지 않는다. 세 pipe와 nonce ACK를 확인한 후에만 종료 권한을 행사한다.
    let mut length = [0u8; 4];
    output.read_exact(&mut length, deadline)?;
    let length = u32::from_le_bytes(length) as usize;
    if length == 0 || length > 4096 {
        return Err(fail("작업자 인증 응답 크기가 올바르지 않습니다."));
    }
    let mut ack = vec![0u8; length];
    output.read_exact(&mut ack, deadline)?;
    if ack != bootstrap.as_bytes() {
        return Err(fail("작업자 인증 응답이 현재 작업과 다릅니다."));
    }
    let connected = own_process(pid, true)?;
    if created(connected.0)? != worker_birth
        || unsafe { WaitForSingleObject(process.0, 0) } != WAIT_TIMEOUT
    {
        return Err(fail("인증 중 문서 작업자 프로세스가 바뀌었습니다."));
    }
    drop(connected);
    let mut worker = OwnedWorker::attach(process)?;
    // SCM 활성화가 끝났다. CLI 작업 동안 portable 등록을 유지할 필요가 없다.
    if let Some(registration) = registration.as_mut() {
        registration.cleanup()?;
    }
    let stdout = thread::spawn(move || output.read_all());
    let stderr = thread::spawn(move || error.read_all());
    input.write_all(&(header.len() as u32).to_le_bytes(), Some(deadline))?;
    input.write_all(&header, Some(deadline))?;
    // stdin payload 실패는 기존 write_all 계약처럼 종료 상태와 stderr로 판정한다.
    if let Some(data) = stdin_payload {
        let _ = input.write_all(data, None);
    }
    drop(input); // payload 없는 도구도 header 뒤 즉시 EOF. 부모 MCP stdin은 상속하지 않는다.
    let status = worker.wait()?;
    let stdout = stdout
        .join()
        .map_err(|_| fail("작업자 표준 출력을 회수하지 못했습니다."))??;
    let stderr = stderr
        .join()
        .map_err(|_| fail("작업자 오류 출력을 회수하지 못했습니다."))??;
    if let Some(registration) = registration.as_mut() {
        registration.cleanup()?;
    }
    Ok(std::process::Output {
        status,
        stdout,
        stderr,
    })
}

fn client_pipe(name: &str, read: bool, parent: u32) -> io::Result<Handle> {
    let handle = unsafe {
        CreateFileW(
            PCWSTR(wide(name).as_ptr()),
            if read {
                FILE_READ_DATA.0
            } else {
                FILE_WRITE_DATA.0
            },
            FILE_SHARE_NONE,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
        .map_err(win)?
    };
    let handle = Handle::new(handle)?;
    let mut pid = 0;
    unsafe {
        GetNamedPipeServerProcessId(handle.0, &mut pid).map_err(win)?;
    }
    if pid != parent {
        return Err(fail("작업자 pipe의 부모 프로세스가 다릅니다."));
    }
    Ok(handle)
}
fn raw_read_exact(handle: HANDLE, mut data: &mut [u8]) -> io::Result<()> {
    while !data.is_empty() {
        let mut count = 0;
        unsafe {
            ReadFile(handle, Some(data), Some(&mut count), None).map_err(win)?;
        }
        if count == 0 {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "작업자 입력 헤더가 끝났습니다.",
            ));
        }
        data = &mut data[count as usize..];
    }
    Ok(())
}
fn raw_write_all(handle: HANDLE, mut data: &[u8]) -> io::Result<()> {
    while !data.is_empty() {
        let mut count = 0;
        unsafe {
            WriteFile(handle, Some(data), Some(&mut count), None).map_err(win)?;
        }
        if count == 0 {
            return Err(io::Error::new(
                io::ErrorKind::WriteZero,
                "작업자 인증 응답을 전달하지 못했습니다.",
            ));
        }
        data = &data[count as usize..];
    }
    Ok(())
}
#[link(name = "ucrt")]
extern "C" {
    fn _open_osfhandle(handle: isize, flags: i32) -> i32;
    fn _dup2(source: i32, target: i32) -> i32;
    fn _close(fd: i32) -> i32;
    fn fflush(stream: *mut c_void) -> i32;
}
fn attach_stdio(handle: HANDLE, number: u32, crt: i32, read: bool) -> io::Result<()> {
    unsafe {
        SetStdHandle(STD_HANDLE(number), handle).map_err(win)?;
    }
    let mut duplicate = HANDLE::default();
    unsafe {
        DuplicateHandle(
            GetCurrentProcess(),
            handle,
            GetCurrentProcess(),
            &mut duplicate,
            0,
            false,
            DUPLICATE_SAME_ACCESS,
        )
        .map_err(win)?;
    }
    let fd = unsafe { _open_osfhandle(duplicate.0 as isize, 0x8000 | if read { 0 } else { 1 }) };
    if fd < 0 {
        unsafe {
            let _ = CloseHandle(duplicate);
        }
        return Err(fail("작업자 CRT 입출력을 연결하지 못했습니다."));
    }
    let result = unsafe { _dup2(fd, crt) };
    // SCM 프로세스에서 CRT 표준 fd가 비어 있으면 새 fd 자체가 target일 수 있다.
    if fd != crt {
        unsafe {
            let _ = _close(fd);
        }
    }
    if result != 0 {
        return Err(fail("작업자 CRT 입출력을 연결하지 못했습니다."));
    }
    Ok(())
}
pub fn serve_if_requested(dispatch: fn(Vec<String>)) -> io::Result<bool> {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(String::as_str) != Some("--opengeul-com-worker") {
        return Ok(false);
    }
    if args.get(2).map(String::as_str) != Some("--clsid")
        || !(args.len() == 4 || (args.len() == 5 && args[4].eq_ignore_ascii_case("-Embedding")))
    {
        return Err(fail("작업자 bootstrap 인수가 올바르지 않습니다."));
    }
    let clsid = guid(&args[3])?;
    // 실제 부모 image/token/creation time과 값이 맞는 fresh portable key만 회수한다.
    // 고정 packaged CLSID는 이 함수에서 삭제 대상으로 취급하지 않는다.
    let registration = Registration::adopt(&args[3])?;
    let _apartment = Apartment::enter()?;
    let (sender, receiver) = mpsc::channel();
    let state = Arc::new(State {
        admission: Admission::default(),
        sender,
    });
    let factory: IClassFactory = Factory { state }.into();
    let class = Class(unsafe {
        CoRegisterClassObject(&clsid, &factory, CLSCTX_LOCAL_SERVER, REGCLS_SINGLEUSE)
            .map_err(win)?
    });
    let deadline = Instant::now() + Duration::from_secs(BOOTSTRAP_SECONDS);
    let metadata = loop {
        if let Some(parent) = registration
            .as_ref()
            .and_then(|value| value.parent.as_ref())
        {
            if unsafe { WaitForSingleObject(parent.0, 0) } == WAIT_OBJECT_0 {
                return Err(fail("연결 전 부모 프로세스가 종료되었습니다."));
            }
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(fail("작업자 연결 시간이 초과되었습니다."));
        }
        match receiver.recv_timeout(remaining.min(Duration::from_secs(1))) {
            Ok(metadata) => break metadata,
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                return Err(fail("작업자 연결이 취소되었습니다."))
            }
        }
    };
    if registration
        .as_ref()
        .is_some_and(|value| value.parent_pid != metadata.parent_pid)
    {
        return Err(fail("등록한 부모와 연결 요청의 부모 프로세스가 다릅니다."));
    }
    let _parent = own_process(metadata.parent_pid, false)?;
    let input = client_pipe(&metadata.pipe("stdin")?, true, metadata.parent_pid)?;
    let output = client_pipe(&metadata.pipe("stdout")?, false, metadata.parent_pid)?;
    let error = client_pipe(&metadata.pipe("stderr")?, false, metadata.parent_pid)?;
    let ack =
        serde_json::to_vec(&metadata).map_err(|_| fail("작업자 인증 응답을 만들지 못했습니다."))?;
    raw_write_all(output.0, &(ack.len() as u32).to_le_bytes())?;
    raw_write_all(output.0, &ack)?;
    let mut length = [0u8; 4];
    raw_read_exact(input.0, &mut length)?;
    let length = u32::from_le_bytes(length) as usize;
    if length == 0 || length > MAX_HEADER {
        return Err(fail("작업자 보호 헤더 상한을 초과했습니다."));
    }
    let mut bytes = vec![0u8; length];
    raw_read_exact(input.0, &mut bytes)?;
    let header = JobHeader::decode(&bytes, &metadata)?;
    drop(class); // 원 CLI 실행 전에 더 이상의 class activation과 job 승인을 닫는다.
    unsafe {
        SetEnvironmentStringsW(PCWSTR(header.environment.as_ptr()))
            .ok()
            .map_err(win)?;
    }
    let directory: Vec<u16> = header.cwd.iter().copied().chain(Some(0)).collect();
    unsafe {
        SetCurrentDirectoryW(PCWSTR(directory.as_ptr()))
            .ok()
            .map_err(win)?;
    }
    attach_stdio(input.0, STD_INPUT_HANDLE.0, 0, true)?;
    attach_stdio(output.0, STD_OUTPUT_HANDLE.0, 1, false)?;
    attach_stdio(error.0, STD_ERROR_HANDLE.0, 2, false)?;
    dispatch(header.args); // main thread: password TLS·직접 process::exit가 원 CLI와 같다.
    std::io::stdout().flush()?;
    std::io::stderr().flush()?;
    unsafe {
        let _ = fflush(ptr::null_mut());
    }
    Ok(true)
}
