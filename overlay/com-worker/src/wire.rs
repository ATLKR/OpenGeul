use serde::{Deserialize, Serialize};
use std::io;
use std::sync::atomic::{AtomicBool, Ordering};

pub const FIXED_CLSID: &str = "c6c4d247-b4f0-563d-a649-4765796e3164";
pub const MAX_HEADER: usize = 1024 * 1024;
const MAX_BOOTSTRAP: usize = 4096;

#[derive(Clone)]
pub struct PeerIdentity {
    pub user: String,
    pub logon: String,
    pub integrity: u32,
    pub elevated: bool,
}
impl PeerIdentity {
    pub fn matches(&self, other: &Self) -> bool {
        !self.user.is_empty()
            && !self.logon.is_empty()
            && self.user == other.user
            && self.logon == other.logon
            && self.integrity == other.integrity
            && self.elevated == other.elevated
    }
}

fn invalid() -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidData,
        "문서 작업자 연결 정보가 올바르지 않습니다.",
    )
}
fn hex(value: &str, count: usize) -> bool {
    value.len() == count
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
pub(crate) fn guid(value: &str) -> bool {
    let parts: Vec<_> = value.split('-').collect();
    parts.len() == 5 && parts.iter().zip([8, 4, 4, 4, 12]).all(|(p, n)| hex(p, n))
}

// Debug를 구현하지 않는다: nonce나 private header가 진단 로그에 들어가지 않는다.
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Bootstrap {
    pub version: u32,
    pub job: String,
    pub nonce: String,
    pub parent_pid: u32,
    pub worker_pid: u32,
}
impl Bootstrap {
    pub fn validate(&self, current_pid: u32) -> io::Result<()> {
        if self.version != 1
            || !guid(&self.job)
            || !hex(&self.nonce, 32)
            || self.parent_pid == 0
            || self.worker_pid == 0
            || self.parent_pid == self.worker_pid
            || self.worker_pid != current_pid
        {
            return Err(invalid());
        }
        Ok(())
    }
    pub fn pipe(&self, role: &str) -> io::Result<String> {
        if !guid(&self.job) || !matches!(role, "stdin" | "stdout" | "stderr") {
            return Err(invalid());
        }
        Ok(format!(
            "\\\\.\\pipe\\OpenGeul.ComWorker.{}.{}",
            self.job, role
        ))
    }
}

#[derive(Default)]
pub struct Admission(AtomicBool);
impl Admission {
    pub fn admit(&self, metadata: &str, current_pid: u32) -> io::Result<Bootstrap> {
        if metadata.len() > MAX_BOOTSTRAP {
            return Err(invalid());
        }
        let value: Bootstrap = serde_json::from_str(metadata).map_err(|_| invalid())?;
        value.validate(current_pid)?;
        self.0
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| invalid())?;
        Ok(value)
    }
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct JobHeader {
    pub version: u32,
    pub nonce: String,
    pub parent_pid: u32,
    pub worker_pid: u32,
    pub args: Vec<String>,
    // UTF16 원본을 유지한다. Windows의 '=C:' 환경 항목도 지우지 않는다.
    pub cwd: Vec<u16>,
    pub environment: Vec<u16>,
}
impl JobHeader {
    pub fn encode(&self) -> io::Result<Vec<u8>> {
        let bytes = serde_json::to_vec(self).map_err(|_| invalid())?;
        if bytes.is_empty() || bytes.len() > MAX_HEADER {
            return Err(invalid());
        }
        Ok(bytes)
    }
    pub fn decode(bytes: &[u8], expected: &Bootstrap) -> io::Result<Self> {
        if bytes.is_empty() || bytes.len() > MAX_HEADER {
            return Err(invalid());
        }
        let value: Self = serde_json::from_slice(bytes).map_err(|_| invalid())?;
        let absolute =
            (value.cwd.len() >= 3 && value.cwd[1] == b':' as u16 && value.cwd[2] == b'\\' as u16)
                || value.cwd.starts_with(&[b'\\' as u16, b'\\' as u16]);
        let env_valid = value.environment.len() >= 2
            && value.environment.ends_with(&[0, 0])
            && !value.environment[..value.environment.len() - 1]
                .windows(2)
                .any(|p| p == [0, 0]);
        if value.version != 1
            || value.nonce != expected.nonce
            || value.parent_pid != expected.parent_pid
            || value.worker_pid != expected.worker_pid
            || value.args.is_empty()
            || value.args.iter().any(|arg| arg.contains('\0'))
            || !absolute
            || value.cwd.contains(&0)
            || !env_valid
        {
            return Err(invalid());
        }
        Ok(value)
    }
}
