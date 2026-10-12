//! Windows 기본 앱/폴더는 OS의 WinRT 활성화 계약으로 연다.
//! 파일·폴더 활성화는 소유 창과 STA 메시지 처리를 사용한다.
use std::{ffi::OsStr, io, path::PathBuf};

#[cfg(windows)]
mod activation;

#[derive(Debug, PartialEq)]
enum Target {
    Uri(String),
    Path(PathBuf),
}

fn target(value: &OsStr) -> io::Result<Target> {
    // URI만 Unicode 문자열이어야 한다. Windows 파일 경로는 OsString 그대로 보존한다.
    if let Some(text) = value.to_str() {
        if text.is_empty() || text.contains('\0') {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "열 대상이 비어 있거나 NUL을 포함합니다",
            ));
        }
        if let Some((scheme, _)) = text.split_once(':') {
            let valid_scheme = scheme
                .as_bytes()
                .first()
                .is_some_and(u8::is_ascii_alphabetic)
                && scheme
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'+' | b'-' | b'.'));
            // X: 및 X:\\... 은 URI가 아닌 Windows 드라이브 경로다.
            if valid_scheme && scheme.len() != 1 {
                if !matches!(
                    scheme.to_ascii_lowercase().as_str(),
                    "http" | "https" | "ms-windows-store"
                ) {
                    return Err(io::Error::new(
                        io::ErrorKind::Unsupported,
                        "지원하지 않는 URI 형식입니다",
                    ));
                }
                return Ok(Target::Uri(text.to_owned()));
            }
        }
    }
    Ok(Target::Path(PathBuf::from(value)))
}

#[cfg(any(windows, test))]
fn accepted(value: bool) -> io::Result<()> {
    if value {
        Ok(())
    } else {
        Err(io::Error::other(
            "Windows가 열기 요청을 수락하지 않았습니다. 연결 앱 또는 사용자 취소를 확인해 주세요",
        ))
    }
}

/// HOP의 open::that 호출 계약을 유지하며 기본 앱·폴더 활성화 결과를 반환한다.
pub fn that<P: AsRef<OsStr>>(value: P) -> io::Result<()> {
    let target = target(value.as_ref())?;
    #[cfg(windows)]
    {
        activation::launch(target, None)
    }
    #[cfg(not(windows))]
    {
        let _ = target;
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "이 어댑터는 Windows 전용입니다",
        ))
    }
}

/// Win32 대화상자의 실제 소유 HWND를 전달한다. 다른 프로세스의 창은 거부한다.
pub fn that_with_owner<P: AsRef<OsStr>>(value: P, owner: isize) -> io::Result<()> {
    let target = target(value.as_ref())?;
    #[cfg(windows)]
    {
        activation::launch(target, Some(owner))
    }
    #[cfg(not(windows))]
    {
        let _ = (target, owner);
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "이 어댑터는 Windows 전용입니다",
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn product_links_are_uris() {
        for text in [
            "https://opengeul.allenlim.net",
            "HTTP://example.com",
            "ms-windows-store://pdp/?ProductId=9PJH0T3PHRMF",
        ] {
            assert_eq!(
                target(OsStr::new(text)).unwrap(),
                Target::Uri(text.to_owned())
            );
        }
    }

    #[test]
    fn unicode_and_drive_paths_are_preserved() {
        for text in [
            "C:\\문서\\한글 파일.pdf",
            "C:보고서.pdf",
            "\\\\서버\\공유\\문서.pdf",
            "새 폴더\\보고서.pdf",
        ] {
            assert_eq!(
                target(OsStr::new(text)).unwrap(),
                Target::Path(PathBuf::from(text))
            );
        }
    }

    #[test]
    fn invalid_or_unsupported_uri_is_an_error() {
        for text in [
            "",
            "https://example.com\0tail",
            "javascript:alert(1)",
            "file:///C:/report.pdf",
            "shell:AppsFolder",
        ] {
            assert!(target(OsStr::new(text)).is_err(), "{text:?}");
        }
    }

    #[test]
    fn windows_rejection_is_not_reported_as_success() {
        assert!(accepted(false).is_err());
        assert!(accepted(true).is_ok());
    }

    #[cfg(windows)]
    #[test]
    fn nonunicode_windows_path_is_not_lossily_changed() {
        use std::os::windows::ffi::OsStringExt;
        let value = std::ffi::OsString::from_wide(&[
            b'C' as u16,
            b':' as u16,
            b'\\' as u16,
            0xd800,
            b'.' as u16,
            b'p' as u16,
            b'd' as u16,
            b'f' as u16,
        ]);
        assert_eq!(target(&value).unwrap(), Target::Path(PathBuf::from(value)));
    }
}
