//! HWPX commands extend, rather than replace, the legacy HWP IPC boundary.
use super::*;

fn ensure_hwpx_target_path(path: &Path) -> Result<(), String> {
    ensure_target_parent(path, "HWPX 저장 경로")?;
    if DocumentFormat::from_path(path)? != DocumentFormat::Hwpx {
        return Err("HWPX 저장에는 .hwpx 확장자가 필요합니다.".into());
    }
    Ok(())
}

#[tauri::command]
pub fn prepare_staged_hwpx_save(app: AppHandle, target_path: String) -> Result<String, String> {
    prepare_staged_file(&app, PathBuf::from(target_path), ensure_hwpx_target_path, staged_hwp_save_path)
}

#[tauri::command]
pub fn commit_staged_hwpx_save(
    app: AppHandle,
    doc_id: String,
    staged_path: String,
    target_path: String,
    expected_revision: Option<u64>,
    allow_external_overwrite: Option<bool>,
    state: State<'_, AppState>,
) -> Result<SaveResult, String> {
    let target = PathBuf::from(target_path);
    ensure_hwpx_target_path(&target)?;
    let result = state.sessions.lock().map_err(|_| "문서 세션 잠금 실패".to_string())?
        .commit_staged_hwpx_save(&doc_id, PathBuf::from(staged_path), target.clone(),
            expected_revision, allow_external_overwrite.unwrap_or(false))?;
    let _ = recent_documents::record_document(&app, &target);
    Ok(result)
}
