//! No upstream self-updater. Development builds update manually through OpenGeul releases.
use serde::Serialize;
use tauri::AppHandle;
#[derive(Debug,Clone,Serialize,PartialEq,Eq,Default)]
#[serde(tag="status",rename_all="camelCase")]
pub enum UpdateNoticeState { #[default] Idle }
#[derive(Default)]
pub struct UpdateManagerState;
impl UpdateManagerState {
    pub fn current_notice(&self) -> UpdateNoticeState { UpdateNoticeState::Idle }
}
pub fn install_startup_update_check(_app: &AppHandle) {}
#[tauri::command]
pub fn get_update_state(_app: AppHandle) -> Result<UpdateNoticeState,String> { Ok(UpdateNoticeState::Idle) }
#[tauri::command]
pub fn start_update_install(_app: AppHandle) -> Result<(),String> { Err("개발판은 OpenGeul GitHub Releases에서 수동으로 업데이트하세요. Store 배포판은 Microsoft Store를 사용합니다.".into()) }
#[tauri::command]
pub fn restart_to_apply_update(_app: AppHandle) -> Result<(),String> { Err("이 배포판에서는 자체 업데이트 설치를 사용하지 않습니다.".into()) }
