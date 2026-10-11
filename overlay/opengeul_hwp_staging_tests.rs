use super::*;

fn dirty_document() -> (DocumentSessionManager, DocumentOpenResult, Vec<u8>) {
    let mut manager = DocumentSessionManager::default();
    let opened = manager.create_document().unwrap();
    let bytes = manager.session(&opened.doc_id).unwrap().core.as_ref().unwrap()
        .export_hwp_native().unwrap();
    manager.mark_document_dirty(&opened.doc_id).unwrap();
    (manager, opened, bytes)
}

fn owned_stage(target: &Path) -> PathBuf {
    target.with_file_name(format!("{}.hop-save-{}.tmp",
        target.file_name().unwrap().to_string_lossy(), Uuid::new_v4().simple()))
}

#[test]
fn save_rejects_staging_destination_alias_and_preserves_original() {
    let (mut manager, opened, bytes) = dirty_document();
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("original.hwp");
    std::fs::write(&target, &bytes).unwrap();
    let result = manager.commit_staged_hwp_save(&opened.doc_id,
        target.clone(), target.clone(), Some(opened.revision), false);
    eprintln!("alias: returned_success={}, target_exists={}, dirty={}, revision={}",
        result.is_ok(), target.exists(), manager.session(&opened.doc_id).unwrap().dirty,
        manager.session(&opened.doc_id).unwrap().revision);
    assert!(result.is_err(), "a document cannot also be its disposable staging file");
    assert_eq!(std::fs::read(target).unwrap(), bytes);
    let session = manager.session(&opened.doc_id).unwrap();
    assert!(session.dirty);
    assert_eq!(session.revision, opened.revision);
}

#[test]
fn save_rejects_unowned_document_as_staging_and_keeps_both_files() {
    let (mut manager, opened, bytes) = dirty_document();
    let dir = tempfile::tempdir().unwrap();
    let staging = dir.path().join("unrelated.hwp");
    let target = dir.path().join("target.hwp");
    std::fs::write(&staging, &bytes).unwrap();
    std::fs::write(&target, b"original target").unwrap();
    let result = manager.commit_staged_hwp_save(&opened.doc_id,
        staging.clone(), target.clone(), Some(opened.revision), false);
    eprintln!("unowned: returned_success={}, staging_exists={}, dirty={}",
        result.is_ok(), staging.exists(), manager.session(&opened.doc_id).unwrap().dirty);
    assert!(result.is_err());
    assert_eq!(std::fs::read(staging).unwrap(), bytes);
    assert_eq!(std::fs::read(target).unwrap(), b"original target");
    assert!(manager.session(&opened.doc_id).unwrap().dirty);
}

#[test]
fn save_owned_staging_replaces_destination_and_removes_only_staging() {
    let (mut manager, opened, bytes) = dirty_document();
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("saved.hwp");
    let staging = owned_stage(&target);
    std::fs::write(&staging, &bytes).unwrap();
    std::fs::write(&target, b"old target").unwrap();
    let result = manager.commit_staged_hwp_save(&opened.doc_id,
        staging.clone(), target.clone(), Some(opened.revision), false).unwrap();
    assert_eq!(std::fs::read(target).unwrap(), bytes);
    assert!(!staging.exists());
    assert!(!result.dirty);
    assert_eq!(result.revision, opened.revision + 1);
}

#[test]
fn save_stale_revision_keeps_target_and_owned_staging() {
    let (mut manager, opened, bytes) = dirty_document();
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("saved.hwp");
    let staging = owned_stage(&target);
    std::fs::write(&staging, &bytes).unwrap();
    std::fs::write(&target, b"old target").unwrap();
    assert!(manager.commit_staged_hwp_save(&opened.doc_id,
        staging.clone(), target.clone(), Some(opened.revision + 1), false).is_err());
    assert_eq!(std::fs::read(target).unwrap(), b"old target");
    assert_eq!(std::fs::read(staging).unwrap(), bytes);
    assert!(manager.session(&opened.doc_id).unwrap().dirty);
}

#[test]
fn save_wrong_destination_extension_keeps_target_and_owned_staging() {
    let (mut manager, opened, bytes) = dirty_document();
    let dir = tempfile::tempdir().unwrap();
    let target = dir.path().join("saved.hwpx");
    let staging = owned_stage(&target);
    std::fs::write(&staging, &bytes).unwrap();
    std::fs::write(&target, b"old target").unwrap();
    assert!(manager.commit_staged_hwp_save(&opened.doc_id,
        staging.clone(), target.clone(), Some(opened.revision), false).is_err());
    assert_eq!(std::fs::read(target).unwrap(), b"old target");
    assert_eq!(std::fs::read(staging).unwrap(), bytes);
    assert!(manager.session(&opened.doc_id).unwrap().dirty);
}
