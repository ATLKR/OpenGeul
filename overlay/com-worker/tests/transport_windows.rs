//! 제품으로 복사하지 않는 실제 Windows COM/stdio 통합 검사 실행 파일.
//! 같은 실행 파일의 별도 SCM worker에서 callback을 수행한다.
#[cfg(not(windows))]
fn main() {
    println!("Windows COM 실행 검사는 이 운영체제에서 실행하지 않았습니다.");
}

#[cfg(windows)]
fn identity() -> serde_json::Value {
    use windows::core::PCWSTR;
    use windows::Win32::{
        Foundation::*,
        Security::*,
        Storage::Packaging::Appx::*,
        System::{Registry::*, SystemInformation::*, Threading::*},
    };
    let wide = |text: &str| text.encode_utf16().chain(Some(0)).collect::<Vec<_>>();
    let mut process_machine = IMAGE_FILE_MACHINE::default();
    let mut native_machine = IMAGE_FILE_MACHINE::default();
    unsafe {
        IsWow64Process2(
            GetCurrentProcess(),
            &mut process_machine,
            Some(&mut native_machine),
        )
        .unwrap();
    }
    let mut token = HANDLE::default();
    unsafe {
        OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token).unwrap();
    }
    let mut elevation = TOKEN_ELEVATION::default();
    let mut length = 0;
    unsafe {
        let result = GetTokenInformation(
            token,
            TokenElevation,
            Some((&mut elevation as *mut TOKEN_ELEVATION).cast()),
            std::mem::size_of::<TOKEN_ELEVATION>() as u32,
            &mut length,
        );
        CloseHandle(token).unwrap();
        result.unwrap();
    }
    let elevated = elevation.TokenIsElevated != 0;
    let mut package_length = 0;
    let package_status = unsafe { GetCurrentPackageFullName(&mut package_length, None) };
    assert!(
        package_status == APPMODEL_ERROR_NO_PACKAGE || package_status == ERROR_INSUFFICIENT_BUFFER
    );
    let packaged = package_status == ERROR_INSUFFICIENT_BUFFER;
    let args: Vec<_> = std::env::args().collect();
    let clsid = args
        .iter()
        .position(|arg| arg == "--clsid")
        .map(|position| args[position + 1].clone());
    let temporary_key_absent = clsid.as_ref().map(|clsid| {
        if clsid == opengeul_com_worker::FIXED_CLSID {
            assert!(packaged);
            return false;
        }
        let mut key = HKEY::default();
        let root = if elevated {
            HKEY_LOCAL_MACHINE
        } else {
            HKEY_CURRENT_USER
        };
        let path = wide(&format!("Software\\Classes\\CLSID\\{{{clsid}}}"));
        let result = unsafe {
            RegOpenKeyExW(
                root,
                PCWSTR(path.as_ptr()),
                None,
                KEY_READ | KEY_WOW64_64KEY,
                &mut key,
            )
        };
        if result == ERROR_SUCCESS {
            unsafe {
                assert_eq!(RegCloseKey(key), ERROR_SUCCESS);
            }
        }
        assert_eq!(
            result, ERROR_FILE_NOT_FOUND,
            "인증 후 작업 시작 전에 portable 등록을 삭제해야 합니다"
        );
        true
    });
    let mut key = HKEY::default();
    let path = wide("Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System");
    let uac = unsafe {
        RegOpenKeyExW(
            HKEY_LOCAL_MACHINE,
            PCWSTR(path.as_ptr()),
            None,
            KEY_READ | KEY_WOW64_64KEY,
            &mut key,
        )
    };
    let enable_lua = if uac == ERROR_SUCCESS {
        let mut value = 0u32;
        let mut kind = REG_VALUE_TYPE::default();
        let mut length = 4;
        let result = unsafe {
            RegQueryValueExW(
                key,
                PCWSTR(wide("EnableLUA").as_ptr()),
                None,
                Some(&mut kind),
                Some((&mut value as *mut u32).cast()),
                Some(&mut length),
            )
        };
        unsafe {
            assert_eq!(RegCloseKey(key), ERROR_SUCCESS);
        }
        if result == ERROR_SUCCESS && kind == REG_DWORD && length == 4 {
            Some(value)
        } else {
            None
        }
    } else {
        None
    };
    serde_json::json!({"pid":unsafe {GetCurrentProcessId()},"imagePath":std::env::current_exe().unwrap(),
        "processMachine":process_machine.0,"nativeMachine":native_machine.0,"elevated":elevated,
        "enableLUA":enable_lua,"packaged":packaged,"bootstrapClsid":clsid,
        "temporaryKeyAbsentBeforeDispatch":temporary_key_absent})
}

#[cfg(windows)]
fn dispatch(args: Vec<String>) {
    use std::io::{Read, Write};
    match args.get(1).map(String::as_str) {
        Some("echo") => println!("{}", serde_json::to_string(&args[2..]).unwrap()),
        Some("stdin") => {
            let mut bytes = Vec::new();
            std::io::stdin().read_to_end(&mut bytes).unwrap();
            // 합성 암호 내용을 반환하지 않고 EOF와 원본 바이트 전달만 판정한다.
            println!("{}", bytes == b"\xef\xbb\xbfsynthetic-password\n");
        }
        Some("stdin-empty") => {
            let mut bytes = Vec::new();
            std::io::stdin().read_to_end(&mut bytes).unwrap();
            println!("{}", bytes.is_empty());
        }
        Some("partial") => {
            println!("{{\"partial\":true}}");
            std::io::stdout().flush().unwrap();
            std::process::exit(1);
        }
        Some("difference") => {
            println!("{{\"different\":true}}");
            std::io::stdout().flush().unwrap();
            std::process::exit(3);
        }
        Some("non-json") => {
            println!("original non-JSON output");
            std::io::stdout().flush().unwrap();
            std::process::exit(3);
        }
        Some("error") => {
            eprintln!("합성 작업 오류");
            std::io::stderr().flush().unwrap();
            std::process::exit(1);
        }
        Some("crash") => {
            // ErrorMode는 dev-only 실행 파일에만 적용한다. 제품 예외 정책은 바꾸지 않는다.
            #[link(name = "kernel32")]
            extern "system" {
                fn SetErrorMode(mode: u32) -> u32;
            }
            unsafe {
                SetErrorMode(0x0001 | 0x0002);
            }
            std::process::abort();
        }
        Some("context") => {
            let cwd = std::env::current_dir().unwrap();
            let expected = std::path::PathBuf::from(&args[2]);
            let environment = std::env::var("OPENGEUL_COM_WORKER_SYNTHETIC_CONTEXT");
            println!(
                "{}",
                cwd == expected && environment.as_deref() == Ok("한글 환경 값")
            );
        }
        Some("identity") => println!("{}", identity()),
        _ => std::process::exit(2),
    }
}

#[cfg(windows)]
fn main() {
    use opengeul_com_worker::{run_cli, serve_if_requested};
    // Rust stdio 접근보다 먼저 SCM bootstrap을 분기한다.
    match serve_if_requested(dispatch) {
        Ok(true) => return,
        Ok(false) => {}
        Err(_) => std::process::exit(1),
    }
    let exe = std::env::current_exe().unwrap();
    let parent = identity();
    let expected_machine = if cfg!(target_arch = "aarch64") {
        0xaa64
    } else {
        0x8664
    };
    assert_eq!(parent["processMachine"], 0);
    assert_eq!(parent["nativeMachine"], expected_machine);
    let run = |args: &[&str], input: Option<&[u8]>| {
        run_cli(
            &exe,
            &args
                .iter()
                .map(|value| (*value).to_string())
                .collect::<Vec<_>>(),
            input,
        )
        .unwrap()
    };
    let echo = run(
        &["echo", "한글 문서 경로", "--", "space and \"quote\""],
        None,
    );
    assert_eq!(echo.status.code(), Some(0));
    assert_eq!(
        serde_json::from_slice::<Vec<String>>(&echo.stdout).unwrap(),
        ["한글 문서 경로", "--", "space and \"quote\""]
    );
    assert!(echo.stderr.is_empty());
    let input = run(&["stdin"], Some(b"\xef\xbb\xbfsynthetic-password\n"));
    assert_eq!(input.status.code(), Some(0));
    assert_eq!(String::from_utf8(input.stdout).unwrap().trim(), "true");
    let empty = run(&["stdin-empty"], None);
    assert_eq!(empty.status.code(), Some(0));
    assert_eq!(String::from_utf8(empty.stdout).unwrap().trim(), "true");
    for (case, code, expected) in [
        ("partial", 1, "{\"partial\":true}"),
        ("difference", 3, "{\"different\":true}"),
        ("non-json", 3, "original non-JSON output"),
    ] {
        let output = run(&[case], None);
        assert_eq!(output.status.code(), Some(code));
        assert_eq!(String::from_utf8(output.stdout).unwrap().trim(), expected);
    }
    let error = run(&["error"], None);
    assert_eq!(error.status.code(), Some(1));
    assert!(error.stdout.is_empty());
    assert_eq!(
        String::from_utf8(error.stderr).unwrap().trim(),
        "합성 작업 오류"
    );
    let crash = run(&["crash"], None);
    assert!(!crash.status.success());
    // crash는 worker에 한정되고 같은 부모가 다음 별도 작업을 수행할 수 있어야 한다.
    assert_eq!(run(&["echo", "after-crash"], None).status.code(), Some(0));
    let cwd = std::env::current_dir().unwrap();
    std::env::set_var("OPENGEUL_COM_WORKER_SYNTHETIC_CONTEXT", "한글 환경 값");
    let context = run_cli(
        &exe,
        &["context".into(), cwd.to_str().unwrap().into()],
        None,
    )
    .unwrap();
    std::env::remove_var("OPENGEUL_COM_WORKER_SYNTHETIC_CONTEXT");
    assert_eq!(context.status.code(), Some(0));
    assert_eq!(String::from_utf8(context.stdout).unwrap().trim(), "true");
    let worker = run(&["identity"], None);
    assert_eq!(worker.status.code(), Some(0));
    let worker: serde_json::Value = serde_json::from_slice(&worker.stdout).unwrap();
    assert_ne!(worker["pid"], parent["pid"]);
    for field in [
        "imagePath",
        "processMachine",
        "nativeMachine",
        "elevated",
        "enableLUA",
        "packaged",
    ] {
        assert_eq!(worker[field], parent[field]);
    }
    assert_eq!(worker["temporaryKeyAbsentBeforeDispatch"], true);
    println!(
        "{}",
        serde_json::json!({"formatVersion":1,"probe":"COM SCM dev-only transport",
        "casesPassed":["unicode-argv","password-stdin-bytes-eof","absent-stdin-eof","partial-exit-1",
            "difference-exit-3","non-json-exit-3","empty-stdout-error","worker-abort",
            "same-parent-next-job","cwd-synthetic-environment","owned-native-worker-key-cleanup"],
        "parent":parent,"worker":worker,"abortExitCode":crash.status.code(),"qualification":false,
        "actualMcpProductTests":false,"installedPackageActivationTested":false})
    );
}
