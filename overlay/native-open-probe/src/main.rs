//! 이 실행 파일은 제품/MSIX에 포함하지 않는다. 실제 Launcher의 수락·오류만 기록한다.
#[cfg(not(windows))]
fn main() {
    eprintln!("이 진단은 실제 Windows 전용입니다");
    std::process::exit(3);
}

#[cfg(windows)]
mod probe {
    use std::{
        ffi::OsString,
        io::{self, BufRead, Read, Write},
        path::Path,
        time::Instant,
    };
    use windows::{
        core::{w, BOOL},
        Win32::{
            Foundation::{HWND, LPARAM},
            System::Com::{
                CoGetApartmentType, CoInitializeEx, CoUninitialize, APTTYPE, APTTYPEQUALIFIER,
                COINIT_APARTMENTTHREADED, COINIT_MULTITHREADED,
            },
            UI::WindowsAndMessaging::{
                CreateWindowExW, DestroyWindow, EnumWindows, GetWindowThreadProcessId,
                IsWindowVisible, WINDOW_EX_STYLE, WS_OVERLAPPEDWINDOW, WS_VISIBLE,
            },
        },
    };

    const FONT_URI: &str = "https://opengeul.allenlim.net/fonts";

    struct Apartment;
    impl Drop for Apartment {
        fn drop(&mut self) {
            unsafe { CoUninitialize() }
        }
    }
    struct Owner(HWND);
    impl Drop for Owner {
        fn drop(&mut self) {
            let _ = unsafe { DestroyWindow(self.0) };
        }
    }

    fn json(value: &str) -> String {
        let mut result = String::from("\"");
        for ch in value.chars() {
            match ch {
                '"' => result.push_str("\\\""),
                '\\' => result.push_str("\\\\"),
                ch if ch <= '\u{1f}' => result.push_str(&format!("\\u{:04x}", ch as u32)),
                ch => result.push(ch),
            }
        }
        result.push('"');
        result
    }

    pub fn setup_error(error: &io::Error) {
        let hresult = error
            .get_ref()
            .and_then(|inner| inner.downcast_ref::<windows::core::Error>())
            .map(|value| value.code().0.to_string())
            .unwrap_or_else(|| "null".to_owned());
        eprintln!(
            "{{\"event\":\"setup-error\",\"hresult\":{hresult},\"error\":{}}}",
            json(&error.to_string())
        );
    }

    fn visible_windows() -> windows::core::Result<Vec<usize>> {
        unsafe extern "system" fn inspect(hwnd: HWND, parameter: LPARAM) -> BOOL {
            let output = unsafe { &mut *(parameter.0 as *mut Vec<usize>) };
            let mut pid = 0;
            unsafe {
                GetWindowThreadProcessId(hwnd, Some(&mut pid));
            }
            if pid == std::process::id() && unsafe { IsWindowVisible(hwnd).as_bool() } {
                output.push(hwnd.0 as usize);
            }
            BOOL(1)
        }
        let mut found = Vec::new();
        unsafe {
            EnumWindows(
                Some(inspect),
                LPARAM((&mut found as *mut Vec<usize>) as isize),
            )?;
        }
        Ok(found)
    }

    fn record(
        mode: &str,
        target: &str,
        apartment: i32,
        owner: Option<&Owner>,
    ) -> io::Result<String> {
        let mut owner_pid = 0;
        let hwnd = owner.map_or(HWND::default(), |value| value.0);
        let visible = if owner.is_some() {
            unsafe {
                GetWindowThreadProcessId(hwnd, Some(&mut owner_pid));
                IsWindowVisible(hwnd).as_bool()
            }
        } else {
            false
        };
        let count = visible_windows().map_err(io::Error::other)?.len();
        let architecture = if cfg!(target_arch = "aarch64") {
            "arm64"
        } else if cfg!(target_arch = "x86_64") {
            "x64"
        } else {
            "unsupported"
        };
        let name = if apartment == 1 { "MTA" } else { "STA" };
        if owner.is_some() {
            if owner_pid != std::process::id()
                || !visible
                || count == 0
                || !matches!(apartment, 0 | 3)
            {
                return Err(io::Error::other(
                    "진단 창의 실제 소유권·STA를 확인하지 못했습니다",
                ));
            }
        } else if apartment != 1 || count != 0 {
            return Err(io::Error::other(
                "MTA URI 진단에 소유 창이 있거나 MTA가 아닙니다",
            ));
        }
        Ok(format!("\"formatVersion\":1,\"observationPhase\":\"before-activation\",\"mode\":{},\"target\":{},\"processId\":{},\"architecture\":{},\"callerApartment\":{},\"callerApartmentType\":{},\"ownerHwnd\":{},\"ownerProcessId\":{},\"ownerVisible\":{},\"ownedVisibleWindowCount\":{}",
            json(mode), json(target), std::process::id(), json(architecture), json(name), apartment,
            hwnd.0 as usize, owner_pid, visible, count))
    }

    pub fn run() -> io::Result<i32> {
        let args: Vec<OsString> = std::env::args_os().collect();
        if args.len() != 3 {
            return Err(io::Error::other(
                "사용법: probe owned-file|owned-folder|owned-uri|ownerless-uri 대상",
            ));
        }
        let mode = args[1]
            .to_str()
            .ok_or_else(|| io::Error::other("진단 모드가 Unicode 문자열이 아닙니다"))?;
        let target = args[2]
            .to_str()
            .ok_or_else(|| io::Error::other("진단 출력 대상이 Unicode 문자열이 아닙니다"))?;
        match mode {
            "owned-file" if Path::new(&args[2]).is_file() => (),
            "owned-folder" if Path::new(&args[2]).is_dir() => (),
            "owned-uri" | "ownerless-uri" if target == FONT_URI => (),
            _ => {
                return Err(io::Error::other(
                    "지원하지 않는 동작·합성 경로·공식 URI입니다",
                ))
            }
        }
        let ownerless = mode == "ownerless-uri";
        unsafe {
            CoInitializeEx(
                None,
                if ownerless {
                    COINIT_MULTITHREADED
                } else {
                    COINIT_APARTMENTTHREADED
                },
            )
            .ok()
            .map_err(io::Error::other)?;
        }
        let _apartment = Apartment;
        let mut apartment = APTTYPE::default();
        let mut qualifier = APTTYPEQUALIFIER::default();
        unsafe {
            CoGetApartmentType(&mut apartment, &mut qualifier).map_err(io::Error::other)?;
        }
        // 등록된 시스템 STATIC 클래스로 이 process에만 속한 표시 중인 최상위 창을 만든다.
        let owner = if ownerless {
            None
        } else {
            Some(Owner(unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("STATIC"),
                    w!("OpenGeul Windows 활성화 진단"),
                    WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                    100,
                    100,
                    480,
                    130,
                    None,
                    None,
                    None,
                    None,
                )
                .map_err(io::Error::other)?
            }))
        };
        let fields = record(mode, target, apartment.0, owner.as_ref())?;
        println!("{{\"event\":\"ready\",{fields}}}");
        io::stdout().flush()?;
        // Controller가 실제 PID/native bitness/live HWND를 관측한 뒤에만 OS 활성화를 허용한다.
        let mut command = String::new();
        io::stdin().lock().take(4).read_line(&mut command)?;
        if command != "GO\n" {
            return Err(io::Error::other("controller의 정확한 GO 확인이 없습니다"));
        }
        let start = Instant::now();
        let result = match mode {
            // 폴더는 제품의 자동 소유 창 발견 경로, 파일·URI는 명시적 실제 소유 HWND 경로.
            "owned-folder" | "ownerless-uri" => open::that(&args[2]),
            _ => open::that_with_owner(&args[2], owner.as_ref().unwrap().0 .0 as isize),
        };
        let elapsed = start.elapsed().as_millis();
        match result {
            Ok(()) => {
                println!("{{\"event\":\"result\",{fields},\"outcome\":\"accepted\",\"hresult\":null,\"errorKind\":null,\"error\":null,\"elapsedMs\":{elapsed}}}");
                Ok(0)
            }
            Err(error) => {
                let hresult = error
                    .get_ref()
                    .and_then(|inner| inner.downcast_ref::<windows::core::Error>())
                    .map(|value| value.code().0.to_string())
                    .unwrap_or_else(|| "null".to_owned());
                println!("{{\"event\":\"result\",{fields},\"outcome\":\"error\",\"hresult\":{hresult},\"errorKind\":{},\"error\":{},\"elapsedMs\":{elapsed}}}",
                    json(&format!("{:?}", error.kind())), json(&error.to_string()));
                Ok(2)
            }
        }
    }
}

#[cfg(windows)]
fn main() {
    let exit_code = match probe::run() {
        Ok(code) => code,
        Err(error) => {
            probe::setup_error(&error);
            3
        }
    };
    std::process::exit(exit_code);
}
