use super::{accepted, Target};
use std::{io, os::windows::ffi::OsStrExt, path::Path, sync::Arc};
use windows::{
    core::{BOOL, HSTRING, Interface, RuntimeType},
    Foundation::Uri,
    Storage::{StorageFile, StorageFolder},
    System::{FolderLauncherOptions, Launcher, LauncherOptions},
    Win32::{
        Foundation::{CloseHandle, HANDLE, HWND, LPARAM, WAIT_OBJECT_0},
        System::{
            Com::{CoGetApartmentType, CoWaitForMultipleHandles, APTTYPE, APTTYPEQUALIFIER, APTTYPE_MAINSTA, APTTYPE_STA, COWAIT_DISPATCH_CALLS, COWAIT_DISPATCH_WINDOW_MESSAGES},
            Threading::{CreateEventW, SetEvent, WaitForSingleObject},
            WinRT::{RoInitialize, RoUninitialize, RO_INIT_MULTITHREADED, RO_INIT_SINGLETHREADED},
        },
        UI::{Shell::IInitializeWithWindow, WindowsAndMessaging::{EnumWindows, GetForegroundWindow, GetWindowThreadProcessId, IsWindowVisible}},
    },
};
use windows_future::{AsyncOperationCompletedHandler, IAsyncOperation};

struct Apartment;

impl Apartment {
    fn sta() -> windows::core::Result<Self> {
        unsafe { RoInitialize(RO_INIT_SINGLETHREADED)?; }
        Ok(Self)
    }

    fn mta() -> windows::core::Result<Self> {
        unsafe { RoInitialize(RO_INIT_MULTITHREADED)?; }
        Ok(Self)
    }
}

impl Drop for Apartment {
    fn drop(&mut self) { unsafe { RoUninitialize(); } }
}

// Kernel event handles may be signaled and waited on from any thread. Arc keeps
// the handle alive through the WinRT completion callback and every wait path.
struct Event(HANDLE);
unsafe impl Send for Event {}
unsafe impl Sync for Event {}

impl Event {
    fn new() -> windows::core::Result<Arc<Self>> {
        Ok(Arc::new(Self(unsafe { CreateEventW(None, true, false, None)? })))
    }
}

impl Drop for Event {
    fn drop(&mut self) { let _ = unsafe { CloseHandle(self.0) }; }
}

struct SignalOnExit(Arc<Event>);
impl Drop for SignalOnExit {
    fn drop(&mut self) { let _ = unsafe { SetEvent(self.0.0) }; }
}

fn sta_wait(event: &Event) -> windows::core::Result<()> {
    unsafe {
        CoWaitForMultipleHandles(
            (COWAIT_DISPATCH_CALLS.0 | COWAIT_DISPATCH_WINDOW_MESSAGES.0) as u32,
            u32::MAX,
            &[event.0],
        )?;
    }
    Ok(())
}

fn caller_wait(event: &Event) -> windows::core::Result<()> {
    let mut kind = APTTYPE::default();
    let mut qualifier = APTTYPEQUALIFIER::default();
    if unsafe { CoGetApartmentType(&mut kind, &mut qualifier) }.is_ok()
        && (kind == APTTYPE_STA || kind == APTTYPE_MAINSTA)
    {
        // A synchronous Tauri command or TaskDialog callback must keep its
        // owner window responsive while the STA worker requests OS UI.
        return sta_wait(event);
    }
    if unsafe { WaitForSingleObject(event.0, u32::MAX) } != WAIT_OBJECT_0 {
        return Err(windows::core::Error::from_win32());
    }
    Ok(())
}

fn complete_sta<T: RuntimeType + 'static>(operation: IAsyncOperation<T>) -> windows::core::Result<T> {
    let event = Event::new()?;
    let completion = Arc::clone(&event);
    operation.SetCompleted(&AsyncOperationCompletedHandler::<T>::new(move |_, _| {
        unsafe { SetEvent(completion.0) }
    }))?;
    sta_wait(&event)?;
    // GetResults preserves the original cancellation/error HRESULT.
    operation.GetResults()
}

fn owned_visible(hwnd: HWND) -> bool {
    let mut process_id = 0;
    unsafe {
        GetWindowThreadProcessId(hwnd, Some(&mut process_id));
        process_id == std::process::id() && IsWindowVisible(hwnd).as_bool()
    }
}

fn owner_window() -> Option<isize> {
    let foreground = unsafe { GetForegroundWindow() };
    if owned_visible(foreground) { return Some(foreground.0 as isize); }
    unsafe extern "system" fn inspect(hwnd: HWND, parameter: LPARAM) -> BOOL {
        let found = unsafe { &mut *(parameter.0 as *mut Option<isize>) };
        if found.is_none() && owned_visible(hwnd) { *found = Some(hwnd.0 as isize); }
        // Keep enumerating so EnumWindows has an unambiguous successful result.
        BOOL(1)
    }
    let mut found: Option<isize> = None;
    let result = unsafe { EnumWindows(Some(inspect), LPARAM((&mut found as *mut Option<isize>) as isize)) };
    if result.is_ok() { found } else { None }
}

fn initialize_owner<T: Interface>(options: &T, owner: isize) -> windows::core::Result<()> {
    let window = HWND(owner as *mut std::ffi::c_void);
    if !owned_visible(window) {
        return Err(windows::core::Error::from_hresult(windows::core::HRESULT(0x80070006_u32 as i32)));
    }
    let initialize: IInitializeWithWindow = options.cast()?;
    unsafe { initialize.Initialize(window) }
}

fn wide_path(path: &Path) -> io::Result<HSTRING> {
    let value: Vec<u16> = path.as_os_str().encode_wide().collect();
    if value.is_empty() || value.contains(&0) {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "파일 경로가 비어 있거나 NUL을 포함합니다"));
    }
    HSTRING::from_wide(&value).map_err(io::Error::other)
}

fn activate_sta(target: Target, owner: isize) -> io::Result<()> {
    let _apartment = Apartment::sta().map_err(io::Error::other)?;
    let result = match target {
        Target::Uri(value) => {
            let uri = Uri::CreateUri(&HSTRING::from(value.as_str())).map_err(io::Error::other)?;
            let options = LauncherOptions::new().map_err(io::Error::other)?;
            initialize_owner(&options, owner).map_err(io::Error::other)?;
            complete_sta(Launcher::LaunchUriWithOptionsAsync(&uri, &options).map_err(io::Error::other)?)
        }
        Target::Path(value) => {
            // absolute preserves OsString; no lossy UTF-8 conversion or command
            // quoting occurs. Windows resolves its ordinary path separators.
            let path = std::path::absolute(value)?;
            let metadata = std::fs::metadata(&path)?;
            let value = wide_path(&path)?;
            if metadata.is_dir() {
                let folder = complete_sta(StorageFolder::GetFolderFromPathAsync(&value).map_err(io::Error::other)?).map_err(io::Error::other)?;
                let options = FolderLauncherOptions::new().map_err(io::Error::other)?;
                initialize_owner(&options, owner).map_err(io::Error::other)?;
                complete_sta(Launcher::LaunchFolderWithOptionsAsync(&folder, &options).map_err(io::Error::other)?)
            } else if metadata.is_file() {
                let file = complete_sta(StorageFile::GetFileFromPathAsync(&value).map_err(io::Error::other)?).map_err(io::Error::other)?;
                let options = LauncherOptions::new().map_err(io::Error::other)?;
                initialize_owner(&options, owner).map_err(io::Error::other)?;
                complete_sta(Launcher::LaunchFileWithOptionsAsync(&file, &options).map_err(io::Error::other)?)
            } else {
                return Err(io::Error::new(io::ErrorKind::InvalidInput, "일반 파일 또는 폴더만 열 수 있습니다"));
            }
        }
    }.map_err(io::Error::other)?;
    accepted(result)
}

fn activate_ownerless_uri(target: Target) -> io::Result<()> {
    let Target::Uri(value) = target else {
        return Err(io::Error::new(io::ErrorKind::NotFound, "파일·폴더를 열 OpenGeul 소유 창을 찾지 못했습니다"));
    };
    // LaunchUriAsync explicitly permits desktop callers outside an ASTA. This
    // handles the WebView installation help before the main window exists.
    let _apartment = Apartment::mta().map_err(io::Error::other)?;
    let uri = Uri::CreateUri(&HSTRING::from(value.as_str())).map_err(io::Error::other)?;
    let result = Launcher::LaunchUriAsync(&uri).map_err(io::Error::other)?.get().map_err(io::Error::other)?;
    accepted(result)
}

pub(super) fn launch(target: Target, requested_owner: Option<isize>) -> io::Result<()> {
    let owner = match requested_owner {
        Some(owner) => {
            if !owned_visible(HWND(owner as *mut std::ffi::c_void)) {
                return Err(io::Error::new(io::ErrorKind::InvalidInput, "OpenGeul이 소유한 표시 중인 창이 아닙니다"));
            }
            Some(owner)
        }
        None => owner_window(),
    };
    let event = Event::new().map_err(io::Error::other)?;
    let completion = Arc::clone(&event);
    let worker = std::thread::Builder::new().name("opengeul-activation".into()).spawn(move || {
        // Signal on both normal return and panic so a caller never waits forever
        // for a Rust panic in this worker. The JoinHandle retains the result.
        let _signal = SignalOnExit(completion);
        match owner {
            Some(owner) => activate_sta(target, owner),
            None => activate_ownerless_uri(target),
        }
    })?;
    caller_wait(&event).map_err(io::Error::other)?;
    worker.join().map_err(|_| io::Error::other("Windows 활성화 작업이 중단됐습니다"))?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn async_error_keeps_its_hresult_and_completes_on_sta() {
        std::thread::spawn(|| {
            let _apartment = Apartment::sta().unwrap();
            let operation = IAsyncOperation::<bool>::spawn(|| Err(windows::core::Error::from_hresult(windows::core::HRESULT(0x80004004_u32 as i32))));
            assert_eq!(complete_sta(operation).unwrap_err().code(), windows::core::HRESULT(0x80004004_u32 as i32));
        }).join().unwrap();
    }

    #[test]
    fn already_completed_operation_is_consumed_without_waiting_for_a_new_callback() {
        std::thread::spawn(|| {
            let _apartment = Apartment::sta().unwrap();
            assert!(complete_sta(IAsyncOperation::<bool>::ready(Ok(true))).unwrap());
        }).join().unwrap();
    }

    #[test]
    fn invalid_owner_does_not_launch_or_use_a_foreign_window() {
        assert!(launch(Target::Uri("https://opengeul.allenlim.net".into()), Some(0)).is_err());
    }

    #[test]
    fn embedded_nul_in_os_path_is_rejected() {
        use std::os::windows::ffi::OsStringExt;
        let path = std::path::PathBuf::from(std::ffi::OsString::from_wide(&[b'C' as u16, b':' as u16, b'\\' as u16, 0xd800, 0]));
        assert!(wide_path(&path).is_err());
    }
}
