//! Microsoft Store 공개 버전만 확인하며 파일 설치와 앱 재시작은 수행하지 않는다.
use serde::{Deserialize, Serialize};
use std::{fmt, sync::Mutex};

pub const STORE_URL: &str = "https://apps.microsoft.com/detail/9PJH0T3PHRMF";
pub const METADATA_URL: &str = "https://opengeul.allenlim.net/api/store-release.json";
pub const MAX_METADATA_BYTES: usize = 8 * 1024;
const CHECK_INTERVAL_SECONDS: u64 = 3600;
const CHECK_FAILURE: &str =
    "업데이트 정보를 확인하지 못했습니다. 인터넷 연결을 확인한 뒤 다시 시도해 주세요.";

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct StoreVersion([u16; 4]);
impl StoreVersion {
    pub fn parse(value: &str) -> Result<Self, CheckError> {
        let parts: Vec<_> = value.split('.').collect();
        if parts.len() != 4 {
            return Err(CheckError::Metadata);
        }
        let mut version = [0; 4];
        for (i, part) in parts.iter().enumerate() {
            if part.is_empty()
                || part.len() > 5
                || !part.bytes().all(|b| b.is_ascii_digit())
                || (part.len() > 1 && part.starts_with('0'))
            {
                return Err(CheckError::Metadata);
            }
            version[i] = part.parse().map_err(|_| CheckError::Metadata)?;
        }
        Ok(Self(version))
    }
    pub fn from_package(value: &str) -> Result<Self, CheckError> {
        if value.split('.').count() != 3 {
            return Err(CheckError::Metadata);
        }
        Self::parse(&format!("{value}.0"))
    }
}
impl fmt::Display for StoreVersion {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}.{}.{}.{}", self.0[0], self.0[1], self.0[2], self.0[3])
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CheckError {
    Network,
    Timeout,
    Metadata,
    TooLarge,
}
#[derive(Debug)]
pub struct StoreRelease {
    pub version: StoreVersion,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ReleaseMetadata {
    format_version: u64,
    app_id: String,
    status: String,
    version: String,
    store_url: String,
    submission_id: String,
}

pub fn append_metadata_chunk(bytes: &mut Vec<u8>, chunk: &[u8]) -> Result<(), CheckError> {
    if chunk.len() > MAX_METADATA_BYTES.saturating_sub(bytes.len()) {
        return Err(CheckError::TooLarge);
    }
    bytes.extend_from_slice(chunk);
    Ok(())
}
pub fn parse_release(bytes: &[u8]) -> Result<StoreRelease, CheckError> {
    if bytes.len() > MAX_METADATA_BYTES {
        return Err(CheckError::TooLarge);
    }
    let metadata: ReleaseMetadata =
        serde_json::from_slice(bytes).map_err(|_| CheckError::Metadata)?;
    let sid = metadata.submission_id.as_bytes();
    if metadata.format_version != 1
        || metadata.app_id != "9PJH0T3PHRMF"
        || metadata.status != "Published"
        || metadata.store_url != STORE_URL
        || sid.is_empty()
        || sid.len() > 25
        || sid[0] == b'0'
        || !sid.iter().all(|b| b.is_ascii_digit())
    {
        return Err(CheckError::Metadata);
    }
    Ok(StoreRelease {
        version: StoreVersion::parse(&metadata.version)?,
    })
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq, Default)]
#[serde(tag = "status", rename_all = "camelCase")]
pub enum UpdateNoticeState {
    #[default]
    Idle,
    Available {
        version: String,
    },
    Error {
        version: String,
        message: String,
    },
}

#[derive(Debug)]
pub enum PreferencesLoadError {
    Missing,
    Unreadable,
}
pub trait PreferencesStore {
    fn reload(&self) -> Result<(), PreferencesLoadError>;
    fn get(&self, key: &str) -> Option<serde_json::Value>;
    fn set(&self, key: &str, value: serde_json::Value);
    fn delete(&self, key: &str);
    fn save(&self) -> Result<(), String>;
}
pub fn load_preferences(store: &impl PreferencesStore) -> (bool, Option<String>) {
    match store.reload() {
        Ok(()) => (
            store
                .get("autoCheck")
                .map_or(true, |v| v.as_bool().unwrap_or(false)),
            store
                .get("dismissedVersion")
                .and_then(|v| v.as_str().map(str::to_owned)),
        ),
        Err(PreferencesLoadError::Missing) => (true, None),
        Err(PreferencesLoadError::Unreadable) => (false, None),
    }
}
pub fn persist_preference(
    store: &impl PreferencesStore,
    key: &str,
    value: serde_json::Value,
) -> Result<(), String> {
    let previous = store.get(key);
    store.set(key, value);
    if let Err(error) = store.save() {
        // 저장 실패 때 변경한 캐시가 이후 다른 설정과 함께 저장되지 않도록 되돌린다.
        match previous {
            Some(previous) => store.set(key, previous),
            None => store.delete(key),
        }
        return Err(error);
    }
    Ok(())
}

#[derive(Clone)]
pub struct UpdateManagerState {
    current: StoreVersion,
    auto_check: bool,
    last_check_seconds: Option<u64>,
    in_flight: bool,
    generation: u64,
    request_generation: u64,
    latest: Option<StoreVersion>,
    dismissed: Option<StoreVersion>,
    manual_error: bool,
}
impl Default for UpdateManagerState {
    fn default() -> Self {
        // 제품 준비 단계가 3파트 숫자 버전을 검증한다. 잘못된 빌드도 자동 확인은 닫는다.
        match StoreVersion::from_package(env!("CARGO_PKG_VERSION")) {
            Ok(current) => Self::new(current),
            Err(_) => {
                let mut state = Self::new(StoreVersion([u16::MAX; 4]));
                state.auto_check = false;
                state
            }
        }
    }
}
impl UpdateManagerState {
    pub fn new(current: StoreVersion) -> Self {
        Self {
            current,
            auto_check: true,
            last_check_seconds: None,
            in_flight: false,
            generation: 0,
            request_generation: 0,
            latest: None,
            dismissed: None,
            manual_error: false,
        }
    }
    pub fn auto_check(&self) -> bool {
        self.auto_check
    }
    pub fn restore_preferences(&mut self, auto: bool, dismissed: Option<String>) {
        self.auto_check = auto;
        self.dismissed = dismissed.and_then(|s| StoreVersion::parse(&s).ok());
    }
    pub fn set_auto_check(&mut self, enabled: bool) {
        if enabled && !self.auto_check {
            self.last_check_seconds = None;
        }
        self.auto_check = enabled;
        if !enabled {
            self.generation = self.generation.wrapping_add(1);
            self.latest = None;
            self.manual_error = false;
        }
    }
    pub fn automatic_wait_seconds(&self, now_seconds: u64) -> u64 {
        if !self.auto_check {
            return CHECK_INTERVAL_SECONDS;
        }
        if self.in_flight {
            return CHECK_INTERVAL_SECONDS;
        }
        self.last_check_seconds.map_or(0, |last| {
            CHECK_INTERVAL_SECONDS.saturating_sub(now_seconds.saturating_sub(last))
        })
    }
    pub fn begin_check(&mut self, now_seconds: u64, manual: bool) -> bool {
        if self.in_flight {
            return false;
        }
        if !manual
            && (!self.auto_check
                || self
                    .last_check_seconds
                    .is_some_and(|last| now_seconds.saturating_sub(last) < CHECK_INTERVAL_SECONDS))
        {
            return false;
        }
        self.in_flight = true;
        self.request_generation = self.generation;
        self.last_check_seconds = Some(now_seconds);
        true
    }
    pub fn finish_check(&mut self, result: Result<StoreRelease, CheckError>, manual: bool) {
        self.in_flight = false;
        if !manual && (!self.auto_check || self.request_generation != self.generation) {
            return;
        }
        match result {
            Ok(release) => {
                self.manual_error = false;
                self.latest = (release.version > self.current).then_some(release.version);
                if manual && self.latest.is_some() {
                    self.dismissed = None;
                }
            }
            Err(_) if manual => self.manual_error = true,
            Err(_) => {} // 자동 실패는 기존 상태를 유지하고 다음 주기에 재시도한다.
        }
    }
    pub fn current_notice(&self) -> UpdateNoticeState {
        if self.manual_error {
            return UpdateNoticeState::Error {
                version: self.current.to_string(),
                message: CHECK_FAILURE.into(),
            };
        }
        match self.latest {
            Some(version) if Some(version) != self.dismissed => UpdateNoticeState::Available {
                version: version.to_string(),
            },
            _ => UpdateNoticeState::Idle,
        }
    }
    pub fn dismiss(&mut self) -> Option<String> {
        if self.manual_error {
            self.manual_error = false;
            self.latest = None;
            return None;
        }
        self.manual_error = false;
        if self.latest.is_some() {
            self.dismissed = self.latest;
        }
        self.latest.map(|v| v.to_string())
    }
    pub fn store_open_target(&self) -> Option<&'static str> {
        matches!(self.current_notice(), UpdateNoticeState::Available { .. }).then_some(STORE_URL)
    }
    pub fn open_store_on_consent(
        &mut self,
        open: impl FnOnce(&str) -> Result<(), String>,
    ) -> Result<Option<String>, String> {
        let url = self
            .store_open_target()
            .ok_or("Microsoft Store에서 확인할 새 버전이 없습니다.")?;
        open(url)?;
        Ok(self.dismiss())
    }
}

// 상태를 바꾼 이벤트는 같은 잠금 안에서 발행한다. OFF/닫기 뒤 낡은 Available을
// 발행하는 창을 없애며, 네트워크 요청 자체는 이 잠금 밖에서 수행한다.
pub fn transition_and_publish<T>(
    state: &Mutex<UpdateManagerState>,
    transition: impl FnOnce(&mut UpdateManagerState) -> Result<T, String>,
    publish: impl FnOnce(&UpdateNoticeState),
) -> Result<T, String> {
    let mut state = state
        .lock()
        .map_err(|_| "업데이트 확인 상태를 읽을 수 없습니다.")?;
    let result = transition(&mut state);
    publish(&state.current_notice());
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::{cell::RefCell, collections::HashMap};

    struct LocalSettings {
        bytes: Option<Vec<u8>>,
        unreadable: bool,
        fail_save: bool,
        cache: RefCell<HashMap<String, serde_json::Value>>,
        saved: RefCell<HashMap<String, serde_json::Value>>,
    }
    impl LocalSettings {
        fn new(bytes: Option<&[u8]>) -> Self {
            Self {
                bytes: bytes.map(Vec::from),
                unreadable: false,
                fail_save: false,
                cache: RefCell::new(HashMap::new()),
                saved: RefCell::new(HashMap::new()),
            }
        }
    }
    impl PreferencesStore for LocalSettings {
        fn reload(&self) -> Result<(), PreferencesLoadError> {
            if self.unreadable {
                return Err(PreferencesLoadError::Unreadable);
            }
            let Some(bytes) = &self.bytes else {
                return Err(PreferencesLoadError::Missing);
            };
            let loaded =
                serde_json::from_slice(bytes).map_err(|_| PreferencesLoadError::Unreadable)?;
            *self.cache.borrow_mut() = loaded;
            Ok(())
        }
        fn get(&self, key: &str) -> Option<serde_json::Value> {
            self.cache.borrow().get(key).cloned()
        }
        fn set(&self, key: &str, value: serde_json::Value) {
            self.cache.borrow_mut().insert(key.into(), value);
        }
        fn delete(&self, key: &str) {
            self.cache.borrow_mut().remove(key);
        }
        fn save(&self) -> Result<(), String> {
            if self.fail_save {
                return Err("저장 실패".into());
            }
            *self.saved.borrow_mut() = self.cache.borrow().clone();
            Ok(())
        }
    }

    #[test]
    fn new_settings_enable_auto_but_malformed_unreadable_and_invalid_types_do_not() {
        assert_eq!(load_preferences(&LocalSettings::new(None)), (true, None));
        for bytes in [b"{".as_slice(), b"[]", b"{\"autoCheck\":\"false\"}"] {
            assert_eq!(
                load_preferences(&LocalSettings::new(Some(bytes))),
                (false, None)
            );
        }
        let mut unavailable = LocalSettings::new(None);
        unavailable.unreadable = true;
        assert_eq!(load_preferences(&unavailable), (false, None));
        assert_eq!(
            load_preferences(&LocalSettings::new(Some(
                br#"{"autoCheck":false,"dismissedVersion":"1.1.4.0"}"#
            ))),
            (false, Some("1.1.4.0".into()))
        );
    }

    #[test]
    fn failed_preference_save_rolls_back_existing_and_new_keys() {
        let mut store = LocalSettings::new(Some(br#"{"autoCheck":true}"#));
        load_preferences(&store);
        store.fail_save = true;
        assert!(persist_preference(&store, "autoCheck", json!(false)).is_err());
        assert_eq!(store.get("autoCheck"), Some(json!(true)));
        assert!(persist_preference(&store, "dismissedVersion", json!("1.1.4.0")).is_err());
        assert_eq!(store.get("dismissedVersion"), None);
        store.fail_save = false;
        persist_preference(&store, "dismissedVersion", json!("1.1.5.0")).unwrap();
        assert_eq!(store.saved.borrow().get("autoCheck"), Some(&json!(true)));
        assert_eq!(
            store.saved.borrow().get("dismissedVersion"),
            Some(&json!("1.1.5.0"))
        );
    }

    #[test]
    fn failed_setting_save_does_not_change_auto_state_or_publish_available_after_off() {
        let mut local = LocalSettings::new(Some(br#"{"autoCheck":false}"#));
        load_preferences(&local);
        local.fail_save = true;
        let mut state = state();
        state.set_auto_check(false);
        let state = Mutex::new(state);
        let published = RefCell::new(Vec::new());
        assert!(transition_and_publish(
            &state,
            |s| {
                persist_preference(&local, "autoCheck", json!(true))?;
                s.set_auto_check(true);
                Ok(())
            },
            |notice| published.borrow_mut().push(notice.clone())
        )
        .is_err());
        assert!(!state.lock().unwrap().auto_check());
        assert_eq!(*published.borrow(), vec![UpdateNoticeState::Idle]);
    }

    fn body(version: &str) -> Vec<u8> {
        serde_json::to_vec(&json!({
            "formatVersion": 1,
            "appId": "9PJH0T3PHRMF",
            "status": "Published",
            "version": version,
            "storeUrl": "https://apps.microsoft.com/detail/9PJH0T3PHRMF",
            "submissionId": "1152921505702042424"
        }))
        .unwrap()
    }

    fn state() -> UpdateManagerState {
        UpdateManagerState::new(StoreVersion::parse("1.1.3.0").unwrap())
    }

    // 테스트 transport와 clock은 이 테스트 유틸리티에만 존재한다.
    fn check(
        state: &mut UpdateManagerState,
        now: u64,
        manual: bool,
        calls: &mut u32,
        transport: impl FnOnce() -> Result<Vec<u8>, CheckError>,
    ) -> bool {
        if !state.begin_check(now, manual) {
            return false;
        }
        *calls += 1;
        state.finish_check(transport().and_then(|b| parse_release(&b)), manual);
        true
    }

    #[test]
    fn canonical_numeric_versions_and_package_version_are_compared() {
        assert!(StoreVersion::parse("1.10.0.0").unwrap() > StoreVersion::parse("1.9.0.0").unwrap());
        assert!(StoreVersion::parse("65535.65535.65535.65535").is_ok());
        assert_eq!(
            StoreVersion::from_package("1.1.3").unwrap().to_string(),
            "1.1.3.0"
        );
        for v in ["1.1.3-beta", "01.1.3", "1.1", "1.1.3.4"] {
            assert!(StoreVersion::from_package(v).is_err(), "{v}");
        }
    }

    #[test]
    fn malformed_noncanonical_and_out_of_range_versions_are_rejected() {
        for v in [
            "1.2.3",
            "1.2.3.4.5",
            "01.2.3.4",
            "+1.2.3.4",
            "1.2.3.65536",
            "1.2.3.-1",
            "１.2.3.4",
            "1.2.3.4 ",
        ] {
            assert!(parse_release(&body(v)).is_err(), "{v}");
        }
    }

    #[test]
    fn valid_owned_published_metadata_is_accepted() {
        assert_eq!(
            parse_release(&body("1.1.4.0")).unwrap().version.to_string(),
            "1.1.4.0"
        );
    }

    #[test]
    fn foreign_unpublished_redirect_urls_and_invalid_submission_ids_are_rejected() {
        let cases = [
            ("appId", json!("OTHER")),
            ("status", json!("Certification")),
            ("status", json!("Release")),
            ("storeUrl", json!("https://evil.example/")),
            ("formatVersion", json!(2)),
            ("formatVersion", json!(true)),
            ("submissionId", json!("0")),
            ("submissionId", json!("0123")),
            ("submissionId", json!("123x")),
            ("submissionId", json!("12345678901234567890123456")),
        ];
        for (key, value) in cases {
            let mut input: serde_json::Value = serde_json::from_slice(&body("1.1.4.0")).unwrap();
            input[key] = value;
            assert!(
                parse_release(&serde_json::to_vec(&input).unwrap()).is_err(),
                "{key}"
            );
        }
    }

    #[test]
    fn extra_missing_duplicate_keys_and_non_utf8_are_rejected() {
        let mut input: serde_json::Value = serde_json::from_slice(&body("1.1.4.0")).unwrap();
        input["extra"] = json!(true);
        assert!(parse_release(&serde_json::to_vec(&input).unwrap()).is_err());
        input.as_object_mut().unwrap().remove("extra");
        input.as_object_mut().unwrap().remove("status");
        assert!(parse_release(&serde_json::to_vec(&input).unwrap()).is_err());
        let duplicate = String::from_utf8(body("1.1.4.0")).unwrap().replacen(
            '{',
            "{\"appId\":\"9PJH0T3PHRMF\",",
            1,
        );
        assert!(parse_release(duplicate.as_bytes()).is_err());
        assert!(parse_release(&[0xff, 0xfe]).is_err());
    }

    #[test]
    fn actual_streamed_bytes_are_bounded_without_trusting_content_length() {
        let mut bytes = Vec::new();
        append_metadata_chunk(&mut bytes, &vec![b' '; MAX_METADATA_BYTES]).unwrap();
        assert_eq!(bytes.len(), MAX_METADATA_BYTES);
        assert_eq!(
            append_metadata_chunk(&mut bytes, b"x"),
            Err(CheckError::TooLarge)
        );
        assert_eq!(bytes.len(), MAX_METADATA_BYTES);
        assert!(parse_release(&vec![b' '; MAX_METADATA_BYTES + 1]).is_err());
    }

    #[test]
    fn startup_is_enabled_and_automatic_checks_wait_one_hour() {
        let mut state = state();
        let mut calls = 0;
        assert!(state.auto_check());
        assert!(check(&mut state, 0, false, &mut calls, || Ok(body(
            "1.1.1.0"
        ))));
        assert!(!check(&mut state, 3599, false, &mut calls, || panic!(
            "조기 요청"
        )));
        assert!(check(&mut state, 3600, false, &mut calls, || Ok(body(
            "1.1.1.0"
        ))));
        assert_eq!(calls, 2);
    }

    #[test]
    fn older_or_same_version_never_shows_a_notice() {
        for version in ["1.1.1.0", "1.1.3.0"] {
            let mut state = state();
            let mut calls = 0;
            check(&mut state, 0, true, &mut calls, || Ok(body(version)));
            assert_eq!(state.current_notice(), UpdateNoticeState::Idle);
            assert_eq!(state.store_open_target(), None);
        }
    }

    #[test]
    fn newer_version_is_announced_but_store_open_requires_an_explicit_action() {
        let mut state = state();
        let mut calls = 0;
        assert_eq!(state.store_open_target(), None);
        check(&mut state, 0, false, &mut calls, || Ok(body("1.1.4.0")));
        assert_eq!(
            state.current_notice(),
            UpdateNoticeState::Available {
                version: "1.1.4.0".into()
            }
        );
        assert_eq!(state.store_open_target(), Some(STORE_URL));
        // 정책 확인 자체는 transport 외에 파일/Store 열기 동작을 호출하지 않는다.
        assert_eq!(calls, 1);
    }

    #[test]
    fn disabled_automatic_check_makes_no_request_but_manual_check_remains_available() {
        let mut state = state();
        let mut calls = 0;
        state.set_auto_check(false);
        assert!(!check(&mut state, 0, false, &mut calls, || panic!(
            "꺼진 자동 요청"
        )));
        assert!(check(&mut state, 0, true, &mut calls, || Ok(body(
            "1.1.4.0"
        ))));
        assert_eq!(calls, 1);
        assert!(matches!(
            state.current_notice(),
            UpdateNoticeState::Available { .. }
        ));
    }

    #[test]
    fn reenable_requests_now_and_in_flight_checks_are_not_duplicated() {
        let mut state = state();
        let mut calls = 0;
        check(&mut state, 0, false, &mut calls, || Ok(body("1.1.1.0")));
        state.set_auto_check(false);
        state.set_auto_check(true);
        assert!(state.begin_check(1, false));
        assert!(!state.begin_check(1, true));
        state.finish_check(parse_release(&body("1.1.4.0")), false);
        assert!(matches!(
            state.current_notice(),
            UpdateNoticeState::Available { .. }
        ));
    }

    #[test]
    fn disabling_during_an_automatic_request_ignores_the_result() {
        let mut state = state();
        assert!(state.begin_check(0, false));
        state.set_auto_check(false);
        state.finish_check(parse_release(&body("1.1.4.0")), false);
        assert_eq!(state.current_notice(), UpdateNoticeState::Idle);
    }

    #[test]
    fn dismissed_version_stays_hidden_and_a_later_version_is_announced() {
        let mut state = state();
        let mut calls = 0;
        check(&mut state, 0, false, &mut calls, || Ok(body("1.1.4.0")));
        assert_eq!(state.dismiss(), Some("1.1.4.0".into()));
        assert_eq!(state.current_notice(), UpdateNoticeState::Idle);
        assert_eq!(state.store_open_target(), None);
        check(&mut state, 3600, false, &mut calls, || Ok(body("1.1.4.0")));
        assert_eq!(state.current_notice(), UpdateNoticeState::Idle);
        check(&mut state, 7200, false, &mut calls, || Ok(body("1.1.5.0")));
        assert!(
            matches!(state.current_notice(), UpdateNoticeState::Available { version } if version == "1.1.5.0")
        );
    }

    #[test]
    fn closing_manual_error_keeps_the_previously_dismissed_version() {
        let mut state = state();
        let mut calls = 0;
        check(&mut state, 0, false, &mut calls, || Ok(body("1.1.4.0")));
        state.dismiss();
        state.set_auto_check(false);
        check(&mut state, 1, true, &mut calls, || Err(CheckError::Network));
        assert_eq!(state.dismiss(), None);
        assert_eq!(state.current_notice(), UpdateNoticeState::Idle);
        state.set_auto_check(true);
        check(&mut state, 2, false, &mut calls, || Ok(body("1.1.4.0")));
        assert_eq!(state.current_notice(), UpdateNoticeState::Idle);
    }

    #[test]
    fn off_then_on_does_not_publish_the_old_automatic_request_result() {
        let mut state = state();
        assert!(state.begin_check(0, false));
        state.set_auto_check(false);
        state.set_auto_check(true);
        state.finish_check(parse_release(&body("1.1.4.0")), false);
        assert_eq!(state.current_notice(), UpdateNoticeState::Idle);
        assert!(state.begin_check(1, false));
    }

    #[test]
    fn reenabled_timer_waits_exactly_one_hour_from_its_new_request() {
        let mut state = state();
        let mut calls = 0;
        assert_eq!(state.automatic_wait_seconds(0), 0);
        check(&mut state, 0, false, &mut calls, || Ok(body("1.1.1.0")));
        state.set_auto_check(false);
        assert_eq!(state.automatic_wait_seconds(1), 3600);
        state.set_auto_check(true);
        assert_eq!(state.automatic_wait_seconds(1), 0);
        check(&mut state, 1, false, &mut calls, || Ok(body("1.1.1.0")));
        assert_eq!(state.automatic_wait_seconds(3600), 1);
        assert_eq!(state.automatic_wait_seconds(3601), 0);
        assert!(check(&mut state, 3601, false, &mut calls, || Ok(body(
            "1.1.1.0"
        ))));
    }

    #[test]
    fn completed_notice_and_setting_off_are_published_in_their_state_order() {
        use std::sync::{mpsc, Arc};
        use std::thread;
        use std::time::Duration;
        let mut initial = state();
        assert!(initial.begin_check(0, false));
        let state = Arc::new(Mutex::new(initial));
        let history = Arc::new(Mutex::new(Vec::new()));
        let (publishing, entered) = mpsc::channel();
        let (release, continue_publish) = mpsc::channel();
        let (off_started, starting_off) = mpsc::channel();
        let state_finish = state.clone();
        let history_finish = history.clone();
        let finish = thread::spawn(move || {
            transition_and_publish(
                &state_finish,
                |s| {
                    s.finish_check(parse_release(&body("1.1.4.0")), false);
                    Ok(())
                },
                |notice| {
                    publishing.send(()).unwrap();
                    continue_publish.recv().unwrap();
                    history_finish.lock().unwrap().push(notice.clone());
                },
            )
            .unwrap();
        });
        entered.recv_timeout(Duration::from_secs(2)).unwrap();
        let state_off = state.clone();
        let history_off = history.clone();
        let off = thread::spawn(move || {
            off_started.send(()).unwrap();
            transition_and_publish(
                &state_off,
                |s| {
                    s.set_auto_check(false);
                    Ok(())
                },
                |notice| history_off.lock().unwrap().push(notice.clone()),
            )
            .unwrap();
        });
        starting_off.recv_timeout(Duration::from_secs(2)).unwrap();
        // 발행이 멈춘 동안 OFF 전이는 같은 실제 잠금을 얻을 수 없다.
        assert!(state.try_lock().is_err());
        release.send(()).unwrap();
        finish.join().unwrap();
        off.join().unwrap();
        assert_eq!(
            *history.lock().unwrap(),
            vec![
                UpdateNoticeState::Available {
                    version: "1.1.4.0".into()
                },
                UpdateNoticeState::Idle
            ]
        );
        assert_eq!(
            state.lock().unwrap().current_notice(),
            UpdateNoticeState::Idle
        );
    }

    #[test]
    fn explicit_manual_check_can_announce_a_previously_dismissed_version() {
        let mut state = state();
        let mut calls = 0;
        state.restore_preferences(false, Some("1.1.4.0".into()));
        check(&mut state, 0, true, &mut calls, || Ok(body("1.1.4.0")));
        assert!(matches!(
            state.current_notice(),
            UpdateNoticeState::Available { .. }
        ));
    }

    #[test]
    fn explicit_consent_opens_only_the_fixed_store_and_failure_preserves_retry() {
        let mut state = state();
        let mut calls = 0;
        assert!(state
            .open_store_on_consent(|_| panic!("공지 없이 Store 열기"))
            .is_err());
        check(&mut state, 0, false, &mut calls, || Ok(body("1.1.4.0")));
        assert!(state
            .open_store_on_consent(|url| {
                assert_eq!(url, STORE_URL);
                Err("연결 실패".into())
            })
            .is_err());
        assert!(matches!(
            state.current_notice(),
            UpdateNoticeState::Available { .. }
        ));
        let mut opens = 0;
        assert_eq!(
            state
                .open_store_on_consent(|url| {
                    assert_eq!(url, STORE_URL);
                    opens += 1;
                    Ok(())
                })
                .unwrap(),
            Some("1.1.4.0".into())
        );
        assert_eq!(opens, 1);
        assert_eq!(state.current_notice(), UpdateNoticeState::Idle);
        assert!(state
            .open_store_on_consent(|_| panic!("중복 Store 열기"))
            .is_err());
    }

    #[test]
    fn stored_preferences_restore_the_same_dismissed_version_for_automatic_checks() {
        let mut state = state();
        let mut calls = 0;
        state.restore_preferences(true, Some("1.1.4.0".into()));
        assert!(state.auto_check());
        check(&mut state, 0, false, &mut calls, || Ok(body("1.1.4.0")));
        assert_eq!(state.current_notice(), UpdateNoticeState::Idle);
    }

    #[test]
    fn offline_timeout_and_malformed_automatic_results_are_silent_and_retry() {
        for error in [
            CheckError::Network,
            CheckError::Timeout,
            CheckError::Metadata,
        ] {
            let mut state = state();
            let mut calls = 0;
            check(&mut state, 0, false, &mut calls, || Err(error));
            assert_eq!(state.current_notice(), UpdateNoticeState::Idle);
            assert!(!check(&mut state, 3599, false, &mut calls, || panic!(
                "실패 후 조기 요청"
            )));
            check(&mut state, 3600, false, &mut calls, || Ok(body("1.1.4.0")));
            assert!(matches!(
                state.current_notice(),
                UpdateNoticeState::Available { .. }
            ));
        }
    }

    #[test]
    fn manual_failures_are_visible_and_manual_retry_clears_the_error() {
        for error in [
            CheckError::Network,
            CheckError::Timeout,
            CheckError::Metadata,
        ] {
            let mut state = state();
            let mut calls = 0;
            check(&mut state, 0, true, &mut calls, || Err(error));
            assert!(matches!(
                state.current_notice(),
                UpdateNoticeState::Error { .. }
            ));
            assert_eq!(state.store_open_target(), None);
            check(&mut state, 1, true, &mut calls, || Ok(body("1.1.4.0")));
            assert!(matches!(
                state.current_notice(),
                UpdateNoticeState::Available { .. }
            ));
        }
    }
}
