//! Microsoft Store 공개 버전 공지. 자체 설치·다운로드·종료·재시작은 수행하지 않는다.
#[path = "store_update_policy.rs"]
mod policy;
#[path = "store_update_transport.rs"]
mod transport;
use crate::state::AppState;
use policy::{transition_and_publish, PreferencesLoadError, PreferencesStore};
pub use policy::{UpdateManagerState, UpdateNoticeState};
use serde::Serialize;
use std::{
    sync::{Arc, OnceLock},
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_store::StoreExt;

const SETTINGS_FILE: &str = "opengeul-updates.json";
const AUTO_KEY: &str = "autoCheck";
const DISMISSED_KEY: &str = "dismissedVersion";
const SETTINGS_ERROR: &str = "업데이트 확인 설정을 저장하지 못했습니다. 다시 시도해 주세요.";

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdatePreferences {
    auto_check: bool,
}
fn clock_seconds() -> u64 {
    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now).elapsed().as_secs()
}
fn timer_notify() -> &'static tokio::sync::Notify {
    static NOTIFY: OnceLock<tokio::sync::Notify> = OnceLock::new();
    NOTIFY.get_or_init(tokio::sync::Notify::new)
}
fn emit_notice(app: &AppHandle, notice: &UpdateNoticeState) {
    let _ = app.emit("hop-update-state", notice);
}
struct NativePreferencesStore(Arc<tauri_plugin_store::Store<tauri::Wry>>);
impl PreferencesStore for NativePreferencesStore {
    fn reload(&self) -> Result<(), PreferencesLoadError> {
        // build()는 초기 파일 오류를 무시하므로 reload 결과를 직접 확인한다.
        match self.0.reload_ignore_defaults() {
            Ok(()) => Ok(()),
            Err(tauri_plugin_store::Error::Io(error))
                if error.kind() == std::io::ErrorKind::NotFound =>
            {
                Err(PreferencesLoadError::Missing)
            }
            Err(_) => Err(PreferencesLoadError::Unreadable),
        }
    }
    fn get(&self, key: &str) -> Option<serde_json::Value> {
        self.0.get(key)
    }
    fn set(&self, key: &str, value: serde_json::Value) {
        self.0.set(key, value);
    }
    fn delete(&self, key: &str) {
        self.0.delete(key);
    }
    fn save(&self) -> Result<(), String> {
        self.0.save().map_err(|_| SETTINGS_ERROR.to_string())
    }
}
fn settings_store(app: &AppHandle) -> Result<NativePreferencesStore, String> {
    app.store_builder(SETTINGS_FILE)
        .disable_auto_save()
        .build()
        .map(NativePreferencesStore)
        .map_err(|_| SETTINGS_ERROR.to_string())
}
fn persist_setting(app: &AppHandle, key: &str, value: serde_json::Value) -> Result<(), String> {
    let store = settings_store(app)?;
    policy::persist_preference(&store, key, value)
}
fn save_dismissed(app: &AppHandle, version: Option<String>) -> Result<(), String> {
    let Some(version) = version else {
        return Ok(());
    };
    persist_setting(app, DISMISSED_KEY, serde_json::json!(version))
}
async fn check(app: AppHandle, manual: bool) -> Result<UpdateNoticeState, String> {
    let state = app.state::<AppState>();
    let previous = {
        let mut updater = state
            .updater
            .lock()
            .map_err(|_| "업데이트 확인 상태를 읽을 수 없습니다.")?;
        let previous = updater.current_notice();
        if !updater.begin_check(clock_seconds(), manual) {
            if manual {
                return Err("업데이트 정보를 확인 중입니다. 잠시 후 다시 시도해 주세요.".into());
            }
            return Ok(previous);
        }
        previous
    };
    // 상태 잠금은 네트워크 요청 중에 유지하지 않는다.
    let result = transport::fetch_release().await;
    let next = transition_and_publish(
        &state.updater,
        |updater| {
            updater.finish_check(result, manual);
            Ok(updater.current_notice())
        },
        |notice| {
            if manual || notice != &previous {
                emit_notice(&app, notice);
            }
        },
    );
    if manual {
        timer_notify().notify_one();
    }
    next
}
pub fn install_startup_update_check(app: &AppHandle) {
    let (auto, dismissed) = match settings_store(app) {
        Ok(store) => policy::load_preferences(&store),
        // 손상된 JSON, 권한 오류 등은 자동 요청을 켜지 않는다.
        Err(_) => (false, None),
    };
    if let Ok(mut updater) = app.state::<AppState>().updater.lock() {
        updater.restore_preferences(auto, dismissed);
    }
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        loop {
            let _ = check(app.clone(), false).await;
            // 설정 변경은 타이머를 깨운다. 마지막 실제 요청 시각에서 1시간을 센다.
            let changed = timer_notify().notified();
            let wait = app
                .state::<AppState>()
                .updater
                .lock()
                .map(|updater| updater.automatic_wait_seconds(clock_seconds()))
                .unwrap_or(3600);
            if wait != 0 {
                let _ = tokio::time::timeout(Duration::from_secs(wait), changed).await;
            }
        }
    });
}
#[tauri::command]
pub fn get_update_state(app: AppHandle) -> Result<UpdateNoticeState, String> {
    let state = app.state::<AppState>();
    let updater = state
        .updater
        .lock()
        .map_err(|_| "업데이트 확인 상태를 읽을 수 없습니다.")?;
    Ok(updater.current_notice())
}
#[tauri::command]
pub async fn check_store_update(app: AppHandle) -> Result<UpdateNoticeState, String> {
    check(app, true).await
}
#[tauri::command]
pub fn get_update_preferences(app: AppHandle) -> Result<UpdatePreferences, String> {
    let state = app.state::<AppState>();
    let updater = state
        .updater
        .lock()
        .map_err(|_| "업데이트 확인 상태를 읽을 수 없습니다.")?;
    Ok(UpdatePreferences {
        auto_check: updater.auto_check(),
    })
}
#[tauri::command]
pub fn set_update_auto_check(app: AppHandle, enabled: bool) -> Result<UpdatePreferences, String> {
    let state = app.state::<AppState>();
    let result = transition_and_publish(
        &state.updater,
        |updater| {
            persist_setting(&app, AUTO_KEY, serde_json::json!(enabled))?;
            updater.set_auto_check(enabled);
            let prefs = UpdatePreferences {
                auto_check: enabled,
            };
            let _ = app.emit("opengeul-update-preferences", &prefs);
            Ok(prefs)
        },
        |notice| emit_notice(&app, notice),
    );
    if result.is_ok() {
        timer_notify().notify_one();
    }
    result
}
#[tauri::command]
pub fn dismiss_store_update(app: AppHandle) -> Result<(), String> {
    let state = app.state::<AppState>();
    transition_and_publish(
        &state.updater,
        |updater| {
            let mut next = updater.clone();
            save_dismissed(&app, next.dismiss())?;
            *updater = next;
            Ok(())
        },
        |notice| emit_notice(&app, notice),
    )
}
#[tauri::command]
pub fn start_update_install(app: AppHandle) -> Result<(), String> {
    let state = app.state::<AppState>();
    transition_and_publish(
        &state.updater,
        |updater| {
            let version = updater.open_store_on_consent(|url| {
                open::that(url)
                    .map_err(|_| "Microsoft Store를 열지 못했습니다. 다시 시도해 주세요.".into())
            })?;
            // Store 열기는 성공했다. 로컬 dismiss 저장 실패로 열기 실패를 표시하지 않는다.
            let _ = save_dismissed(&app, version);
            Ok(())
        },
        |notice| emit_notice(&app, notice),
    )
}
#[tauri::command]
pub fn restart_to_apply_update(_app: AppHandle) -> Result<(), String> {
    Err("업데이트 설치는 Microsoft Store에서 진행합니다. OpenGeul은 자동으로 종료하거나 다시 시작하지 않습니다.".into())
}
