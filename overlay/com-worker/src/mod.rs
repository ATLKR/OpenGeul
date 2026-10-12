//! Windows COM SCM이 실행한 별도 프로세스에 원 CLI 작업을 전달한다.
//! 문서 인수·암호·환경은 인증된 로컬 pipe로만 전달한다.
mod wire;
pub use wire::{Admission, Bootstrap, JobHeader, PeerIdentity, FIXED_CLSID, MAX_HEADER};

#[cfg(windows)]
mod windows;
#[cfg(windows)]
pub use windows::{run_cli, serve_if_requested};
