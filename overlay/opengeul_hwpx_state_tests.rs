use super::*;

fn stage(target: &Path, bytes: &[u8]) -> PathBuf {
    let name = format!("{}.hop-save-{}.tmp", target.file_name().unwrap().to_string_lossy(), Uuid::new_v4().simple());
    let path = target.with_file_name(name);
    std::fs::write(&path, bytes).unwrap();
    path
}
fn fixture() -> (DocumentSessionManager, DocumentOpenResult, Vec<u8>) {
    let mut manager = DocumentSessionManager::default();
    let opened = manager.create_document().unwrap();
    manager.mutate_document(&opened.doc_id, "insertText",
        json!({"sec":0,"para":0,"charOffset":0,"text":"계약서 & <견적> OpenGeul Ω"}), Some(1)).unwrap();
    let bytes = manager.session(&opened.doc_id).unwrap().core.as_ref().unwrap().export_hwpx_native().unwrap();
    (manager, opened, bytes)
}
#[test]
fn hwpx_commit_roundtrip_preserves_bytes_format_revision_and_fingerprint() {
    let (mut manager, opened, bytes) = fixture();
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("계약서.HWPX");
    let staging = stage(&target, &bytes);
    let saved = manager.commit_staged_hwpx_save(&opened.doc_id, staging.clone(), target.clone(), Some(2), false).unwrap();
    assert_eq!(saved.format, DocumentFormat::Hwpx);
    assert_eq!(saved.revision, 3);
    assert!(!saved.dirty);
    assert!(!staging.exists());
    assert_eq!(std::fs::read(&target).unwrap(), bytes);
    let reopened = editable_core_from_bytes(&bytes, "parse", "convert").unwrap();
    assert!(reopened.page_count() > 0);
    assert!(!manager.external_modification_status(&opened.doc_id, Some(target)).unwrap().changed);
}
#[test]
fn hwpx_three_edit_save_reopen_cycles() {
    let (mut manager, opened, mut bytes) = fixture();
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("cycles.hwpx");
    let mut revision = 2;
    for text in ["추가1 ", "& <추가2> ", "追加3 Ω "] {
        let staging = stage(&target, &bytes);
        let saved = manager.commit_staged_hwpx_save(&opened.doc_id, staging, target.clone(), Some(revision), false).unwrap();
        revision = saved.revision;
        let mutated = manager.mutate_document(&opened.doc_id, "insertText",
            json!({"sec":0,"para":0,"charOffset":0,"text":text}), Some(revision)).unwrap();
        revision = mutated.revision;
        bytes = manager.session(&opened.doc_id).unwrap().core.as_ref().unwrap().export_hwpx_native().unwrap();
        assert!(editable_core_from_bytes(&bytes, "parse", "convert").is_ok());
    }
}
#[test]
fn hwpx_invalid_bytes_never_replace_original_or_clear_dirty_state() {
    for bytes in [b"".as_slice(), b"PK\x03\x04broken zip", b"not zip"] {
        let (mut manager, opened, _) = fixture();
        let dir = tempfile::tempdir().unwrap();
        let target = dir.path().join("original.hwpx");
        std::fs::write(&target, b"original unchanged").unwrap();
        let staging = stage(&target, bytes);
        assert!(manager.commit_staged_hwpx_save(&opened.doc_id, staging.clone(), target.clone(), Some(2), false).is_err());
        assert_eq!(std::fs::read(target).unwrap(), b"original unchanged");
        assert!(staging.exists());
        assert!(manager.session(&opened.doc_id).unwrap().dirty);
        assert_eq!(manager.session(&opened.doc_id).unwrap().revision, 2);
    }
}
#[test]
fn hwpx_rejects_hwp_bytes_even_with_hwpx_extension() {
    let (mut manager, opened, _) = fixture();
    let bytes = manager.session(&opened.doc_id).unwrap().core.as_ref().unwrap().export_hwp_native().unwrap();
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("wrong.hwpx");
    let staging = stage(&target, &bytes);
    assert!(manager.commit_staged_hwpx_save(&opened.doc_id, staging, target.clone(), Some(2), false).unwrap_err().contains("HWPX ZIP"));
    assert!(!target.exists());
}
#[test]
fn hwpx_rejects_wrong_target_extension_and_stale_revision() {
    let (mut manager, opened, bytes) = fixture();
    let dir = tempfile::tempdir().unwrap();
    let wrong = dir.path().join("wrong.hwp");
    let staging = stage(&wrong, &bytes);
    assert!(manager.commit_staged_hwpx_save(&opened.doc_id, staging.clone(), wrong.clone(), Some(2), false).is_err());
    assert!(!wrong.exists());
    assert!(manager.commit_staged_hwpx_save(&opened.doc_id, staging, dir.path().join("right.hwpx"), Some(999), false).unwrap_err().contains("revision"));
}
#[test]
fn hwpx_external_change_requires_explicit_overwrite() {
    let (mut manager, opened, bytes) = fixture();
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("external.hwpx");
    let staging = stage(&target, &bytes);
    manager.commit_staged_hwpx_save(&opened.doc_id, staging, target.clone(), Some(2), false).unwrap();
    std::fs::write(&target, b"outside change").unwrap();
    let staging = stage(&target, &bytes);
    assert!(manager.commit_staged_hwpx_save(&opened.doc_id, staging.clone(), target.clone(), Some(3), false).unwrap_err().contains("EXTERNAL_MODIFICATION"));
    assert_eq!(std::fs::read(&target).unwrap(), b"outside change");
    manager.commit_staged_hwpx_save(&opened.doc_id, staging, target.clone(), Some(3), true).unwrap();
    assert_eq!(std::fs::read(target).unwrap(), bytes);
}
#[test]
fn hwpx_rejects_unowned_staging_and_preserves_it() {
    let (mut manager, opened, bytes) = fixture();
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("target.hwpx");
    let unrelated = dir.path().join("important.hwpx");
    std::fs::write(&unrelated, &bytes).unwrap();
    assert!(manager.commit_staged_hwpx_save(&opened.doc_id, unrelated.clone(), target.clone(), Some(2), false).is_err());
    assert_eq!(std::fs::read(unrelated).unwrap(), bytes);
    let another = tempfile::tempdir().unwrap();
    let escaped = stage(&another.path().join("target.hwpx"), &bytes);
    assert!(manager.commit_staged_hwpx_save(&opened.doc_id, escaped.clone(), target.clone(), Some(2), false).is_err());
    assert!(escaped.exists());
    assert!(!target.exists());
}
#[test]
fn hwpx_failed_atomic_replacement_keeps_dirty_state() {
    let (mut manager, opened, bytes) = fixture();
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("directory.hwpx");
    std::fs::create_dir(&target).unwrap();
    let staging = stage(&target, &bytes);
    assert!(manager.commit_staged_hwpx_save(&opened.doc_id, staging, target.clone(), Some(2), false).is_err());
    assert!(target.is_dir());
    assert!(manager.session(&opened.doc_id).unwrap().dirty);
    assert_eq!(manager.session(&opened.doc_id).unwrap().revision, 2);
}
