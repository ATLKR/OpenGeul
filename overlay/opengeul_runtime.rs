use std::{ffi::c_void, ptr};

const INSTALL_URL: &str = "https://developer.microsoft.com/microsoft-edge/webview2/#download-section";
const MB_YESNO: u32 = 0x00000004;
const MB_ICONERROR: u32 = 0x00000010;
const MB_SETFOREGROUND: u32 = 0x00010000;
const IDYES: i32 = 6;

#[link(name = "user32")]
extern "system" {
    fn MessageBoxW(window: *mut c_void, text: *const u16, caption: *const u16, flags: u32) -> i32;
}

pub fn ready() -> bool {
    if tauri::webview_version().is_ok() { return true; }
    let instructions = format!(
        "Microsoft Edge WebView2 Runtime을 찾을 수 없습니다.\n\nMicrosoft 공식 페이지에서 Evergreen Runtime을 설치한 뒤 OpenGeul을 다시 실행하세요.\n\n{INSTALL_URL}\n\n지금 설치 페이지를 열까요?"
    );
    if message(&instructions, MB_YESNO) == IDYES {
        if let Err(error) = open::that(INSTALL_URL) {
            eprintln!("WebView2 설치 페이지 열기 실패: {error}");
            message(&format!("설치 페이지를 열지 못했습니다. 브라우저에 아래 주소를 입력해 주세요.\n\n{INSTALL_URL}"), 0);
        }
    }
    false
}

fn message(text: &str, buttons: u32) -> i32 {
    let body: Vec<u16> = text.encode_utf16().chain(Some(0)).collect();
    let title: Vec<u16> = "OpenGeul".encode_utf16().chain(Some(0)).collect();
    let result = unsafe {
        MessageBoxW(ptr::null_mut(), body.as_ptr(), title.as_ptr(), buttons | MB_ICONERROR | MB_SETFOREGROUND)
    };
    if result == 0 { eprintln!("OpenGeul 안내 표시 실패: {text}"); }
    result
}
