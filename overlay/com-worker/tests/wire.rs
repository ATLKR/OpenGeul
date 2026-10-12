use opengeul_com_worker::{Admission, Bootstrap, JobHeader, PeerIdentity, FIXED_CLSID, MAX_HEADER};

fn bootstrap() -> Bootstrap {
    Bootstrap {
        version: 1,
        job: "12345678-1234-4321-8765-123456789abc".into(),
        nonce: "0123456789abcdef0123456789abcdef".into(),
        parent_pid: 123,
        worker_pid: 456,
    }
}
fn header() -> JobHeader {
    let b = bootstrap();
    JobHeader {
        version: b.version,
        nonce: b.nonce,
        parent_pid: b.parent_pid,
        worker_pid: b.worker_pid,
        args: vec![
            "rhwp".into(),
            "export-text".into(),
            "한글 문서.hwp".into(),
            "--password-stdin".into(),
        ],
        cwd: "C:\\한글 폴더".encode_utf16().collect(),
        environment: "A=one\0=C:=C:\\한글 폴더\0\0".encode_utf16().collect(),
    }
}

#[test]
fn protected_header_preserves_argv_and_raw_environment() {
    let encoded = header().encode().unwrap();
    let decoded = JobHeader::decode(&encoded, &bootstrap()).unwrap();
    assert_eq!(decoded.args, header().args);
    assert_eq!(decoded.environment, header().environment);
    assert_eq!(decoded.cwd, header().cwd);
    assert_eq!(FIXED_CLSID, "c6c4d247-b4f0-563d-a649-4765796e3164");
}
#[test]
fn admission_is_single_job_and_rejected_metadata_does_not_consume_it() {
    let admission = Admission::default();
    let mut b = bootstrap();
    b.worker_pid = 999;
    assert!(admission
        .admit(&serde_json::to_string(&b).unwrap(), 456)
        .is_err());
    assert!(admission
        .admit(&serde_json::to_string(&bootstrap()).unwrap(), 456)
        .is_ok());
    assert!(admission
        .admit(&serde_json::to_string(&bootstrap()).unwrap(), 456)
        .is_err());
}
#[test]
fn wrong_nonce_parent_worker_or_version_is_rejected() {
    for field in 0..4 {
        let mut h = header();
        match field {
            0 => h.nonce = "f".repeat(32),
            1 => h.parent_pid = 999,
            2 => h.worker_pid = 999,
            _ => h.version = 2,
        };
        let encoded = serde_json::to_vec(&h).unwrap();
        assert!(JobHeader::decode(&encoded, &bootstrap()).is_err());
    }
}
#[test]
fn malformed_duplicate_unknown_and_oversize_headers_are_rejected() {
    let encoded = header().encode().unwrap();
    let mut duplicate = String::from_utf8(encoded.clone()).unwrap();
    duplicate.insert_str(1, "\"version\":1,");
    let mut unknown = String::from_utf8(encoded).unwrap();
    unknown.insert_str(1, "\"untrusted\":true,");
    for data in [
        b"{broken".to_vec(),
        duplicate.into_bytes(),
        unknown.into_bytes(),
        vec![b' '; MAX_HEADER + 1],
    ] {
        assert!(JobHeader::decode(&data, &bootstrap()).is_err());
    }
}
#[test]
fn embedded_nul_argv_relative_cwd_and_invalid_environment_are_rejected() {
    for field in 0..4 {
        let mut h = header();
        match field {
            0 => h.args.push("bad\0arg".into()),
            1 => h.cwd = "relative".encode_utf16().collect(),
            2 => {
                h.environment.pop();
            }
            _ => h.environment = "A=one\0\0B=two\0\0".encode_utf16().collect(),
        };
        assert!(JobHeader::decode(&serde_json::to_vec(&h).unwrap(), &bootstrap()).is_err());
    }
}
#[test]
fn bootstrap_names_are_local_fixed_namespace_and_guid_checked() {
    let b = bootstrap();
    assert_eq!(
        b.pipe("stdin").unwrap(),
        "\\\\.\\pipe\\OpenGeul.ComWorker.12345678-1234-4321-8765-123456789abc.stdin"
    );
    assert!(b.pipe("unknown").is_err());
    let mut bad = b;
    bad.job = "..\\foreign".into();
    assert!(bad.validate(456).is_err());
}
#[test]
fn same_user_does_not_allow_a_different_logon_integrity_or_elevation() {
    let identity = PeerIdentity {
        user: "S-1-5-21-1".into(),
        logon: "S-1-5-5-1-2".into(),
        integrity: 0x3000,
        elevated: true,
    };
    assert!(identity.matches(&identity));
    for field in 0..4 {
        let mut changed = identity.clone();
        match field {
            0 => changed.user = "S-1-5-21-2".into(),
            1 => changed.logon = "S-1-5-5-1-3".into(),
            2 => changed.integrity = 0x2000,
            _ => changed.elevated = false,
        };
        assert!(!identity.matches(&changed));
    }
}
#[test]
fn simultaneous_begin_requests_accept_exactly_one_job() {
    let admission = std::sync::Arc::new(Admission::default());
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(16));
    let metadata = serde_json::to_string(&bootstrap()).unwrap();
    let threads: Vec<_> = (0..16)
        .map(|_| {
            let admission = admission.clone();
            let barrier = barrier.clone();
            let metadata = metadata.clone();
            std::thread::spawn(move || {
                barrier.wait();
                admission.admit(&metadata, 456).is_ok()
            })
        })
        .collect();
    assert_eq!(
        threads
            .into_iter()
            .map(|thread| u32::from(thread.join().unwrap()))
            .sum::<u32>(),
        1
    );
}
