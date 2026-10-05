//! HWPX persistence. This child module can reuse the existing private session guards.
use super::*;

fn validate_staging_path(staged: &Path, target: &Path) -> Result<(), String> {
    let parent = |p: &Path| -> Result<PathBuf, String> {
        std::fs::canonicalize(p.parent().ok_or("저장 상위 경로가 없습니다.")?)
            .map_err(|e| format!("저장 상위 경로 확인 실패: {e}"))
    };
    let prefix = format!("{}.hop-save-", target.file_name().ok_or("파일 이름이 없습니다.")?.to_string_lossy());
    let name = staged.file_name().ok_or("staging 이름이 없습니다.")?.to_string_lossy();
    let token = name.strip_prefix(&prefix).and_then(|s| s.strip_suffix(".tmp"));
    if parent(staged)? != parent(target)? || !token.is_some_and(|s| s.len() == 32 && s.bytes().all(|b| b.is_ascii_hexdigit())) {
        return Err("저장 대상에 속하지 않은 staging 경로입니다.".into());
    }
    let metadata = std::fs::symlink_metadata(staged).map_err(|e| format!("staging 파일 확인 실패: {e}"))?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || same_path(staged, target) {
        return Err("일반 staging 파일만 저장할 수 있습니다.".into());
    }
    if metadata.len() > 512 * 1024 * 1024 {
        return Err("HWPX 저장 파일이 512 MiB 제한을 초과했습니다.".into());
    }
    Ok(())
}

impl DocumentSessionManager {
    pub fn commit_staged_hwpx_save(
        &mut self,
        doc_id: &str,
        staged_path: PathBuf,
        target_path: PathBuf,
        expected_revision: Option<u64>,
        allow_external_overwrite: bool,
    ) -> Result<SaveResult, String> {
        let session = self.session_mut(doc_id)?;
        session.check_revision(expected_revision)?;
        if DocumentFormat::from_path(&target_path)? != DocumentFormat::Hwpx {
            return Err("HWPX 저장에는 .hwpx 확장자가 필요합니다.".into());
        }
        if !allow_external_overwrite { session.check_external_modification_for_path(&target_path)?; }
        validate_staging_path(&staged_path, &target_path)?;
        let bytes = std::fs::read(&staged_path).map_err(|e| format!("staging 읽기 실패: {e}"))?;
        if bytes.len() > 512 * 1024 * 1024 || !bytes.starts_with(b"PK\x03\x04") {
            return Err("HWPX 경로에는 검증된 HWPX ZIP 데이터를 저장해야 합니다.".into());
        }
        // A ZIP signature alone is NOT validation: parse required HWPX content before replacing anything.
        let core = editable_core_from_bytes(&bytes, "HWPX 저장 검증 실패", "HWPX 문서 변환 실패")?;
        // Parsing may take time. Recheck the original immediately before replacement.
        if !allow_external_overwrite { session.check_external_modification_for_path(&target_path)?; }
        atomic_write(&target_path, &bytes)?;
        let fingerprint = file_fingerprint_from_bytes(&target_path, &bytes)
            .map_err(|e| format!("저장 후 파일 상태 확인 실패: {e}"))?;
        session.page_count = core.page_count();
        session.core = Some(core);
        session.source_path = Some(target_path);
        session.source_format = DocumentFormat::Hwpx;
        session.source_fingerprint = Some(fingerprint);
        session.revision += 1;
        session.dirty = false;
        session.page_svg_cache.clear();
        let _ = std::fs::remove_file(&staged_path);
        Ok(session.save_result())
    }
}

#[cfg(test)]
#[path = "opengeul_hwpx_state_tests.rs"]
mod tests;
