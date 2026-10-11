//! 고정 공개 메타데이터의 제한된 HTTPS 요청. 사용자 문서나 식별자는 보내지 않는다.
use super::policy::{
    append_metadata_chunk, parse_release, CheckError, StoreRelease, MAX_METADATA_BYTES,
    METADATA_URL,
};
use std::time::Duration;

fn client_builder() -> reqwest::ClientBuilder {
    let _ = rustls::crypto::ring::default_provider().install_default();
    reqwest::Client::builder()
        .https_only(true)
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(3))
        .timeout(Duration::from_secs(8))
}
fn request_error(error: reqwest::Error) -> CheckError {
    if error.is_timeout() {
        CheckError::Timeout
    } else {
        CheckError::Network
    }
}
async fn fetch_using(client: &reqwest::Client, url: &str) -> Result<StoreRelease, CheckError> {
    let mut response = client.get(url).send().await.map_err(request_error)?;
    if response.status() != reqwest::StatusCode::OK {
        return Err(CheckError::Metadata);
    }
    if response
        .content_length()
        .is_some_and(|n| n > MAX_METADATA_BYTES as u64)
    {
        return Err(CheckError::TooLarge);
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(request_error)? {
        append_metadata_chunk(&mut bytes, &chunk)?;
    }
    parse_release(&bytes)
}
pub async fn fetch_release() -> Result<StoreRelease, CheckError> {
    let client = client_builder().build().map_err(request_error)?;
    fetch_using(&client, METADATA_URL).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{Read, Write},
        net::TcpListener,
        thread,
    };

    fn server(response: &'static [u8]) -> (String, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}/", listener.local_addr().unwrap());
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(2)))
                .unwrap();
            let mut request = [0; 4096];
            let n = stream.read(&mut request).unwrap();
            let request = std::str::from_utf8(&request[..n]).unwrap();
            assert!(request.starts_with("GET / HTTP/1.1"));
            assert!(!request.to_ascii_lowercase().contains("authorization:"));
            assert!(!request.to_ascii_lowercase().contains("cookie:"));
            stream.write_all(response).unwrap();
        });
        (url, handle)
    }
    // 운영 client와 동일한 redirect/body 정책을 로컬 HTTP fixture로 검사한다.
    fn local_client() -> reqwest::Client {
        client_builder().https_only(false).build().unwrap()
    }

    #[tokio::test]
    async fn production_client_refuses_plaintext_before_opening_a_connection() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let url = format!("http://{}/", listener.local_addr().unwrap());
        let client = client_builder().build().unwrap();
        assert_eq!(
            fetch_using(&client, &url).await.err(),
            Some(CheckError::Network)
        );
        assert!(listener.accept().is_err());
    }

    #[tokio::test]
    async fn redirect_response_is_rejected_without_requesting_its_destination() {
        let target = TcpListener::bind("127.0.0.1:0").unwrap();
        target.set_nonblocking(true).unwrap();
        let response = format!("HTTP/1.1 302 Found\r\nLocation: http://{}/\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", target.local_addr().unwrap());
        let (url, handle) = server(Box::leak(response.into_bytes().into_boxed_slice()));
        assert_eq!(
            fetch_using(&local_client(), &url).await.err(),
            Some(CheckError::Metadata)
        );
        handle.join().unwrap();
        assert!(target.accept().is_err());
    }

    #[tokio::test]
    async fn successful_transport_accepts_exact_owned_published_json() {
        let body = br#"{"formatVersion":1,"appId":"9PJH0T3PHRMF","status":"Published","version":"1.1.4.0","storeUrl":"https://apps.microsoft.com/detail/9PJH0T3PHRMF","submissionId":"1152921505702042424"}"#;
        let mut response = format!(
            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        )
        .into_bytes();
        response.extend_from_slice(body);
        let (url, handle) = server(Box::leak(response.into_boxed_slice()));
        assert_eq!(
            fetch_using(&local_client(), &url)
                .await
                .unwrap()
                .version
                .to_string(),
            "1.1.4.0"
        );
        handle.join().unwrap();
    }

    #[tokio::test]
    async fn declared_and_actual_chunked_oversize_responses_are_rejected() {
        let (url, handle) =
            server(b"HTTP/1.1 200 OK\r\nContent-Length: 8193\r\nConnection: close\r\n\r\n");
        assert_eq!(
            fetch_using(&local_client(), &url).await.err(),
            Some(CheckError::TooLarge)
        );
        handle.join().unwrap();
        let mut response =
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n2001\r\n"
                .to_vec();
        response.extend_from_slice(&vec![b' '; MAX_METADATA_BYTES + 1]);
        response.extend_from_slice(b"\r\n0\r\n\r\n");
        let (url, handle) = server(Box::leak(response.into_boxed_slice()));
        assert_eq!(
            fetch_using(&local_client(), &url).await.err(),
            Some(CheckError::TooLarge)
        );
        handle.join().unwrap();
    }

    #[tokio::test]
    async fn unavailable_listener_and_stalled_response_have_distinct_bounded_errors() {
        let unavailable = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}/", unavailable.local_addr().unwrap());
        drop(unavailable);
        assert_eq!(
            fetch_using(&local_client(), &url).await.err(),
            Some(CheckError::Network)
        );
        let stalled = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}/", stalled.local_addr().unwrap());
        let handle = thread::spawn(move || {
            let (mut stream, _) = stalled.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(2)))
                .unwrap();
            let mut request = [0; 4096];
            stream.read(&mut request).unwrap();
            thread::sleep(Duration::from_millis(100));
        });
        let bounded = client_builder()
            .https_only(false)
            .timeout(Duration::from_millis(30))
            .build()
            .unwrap();
        assert_eq!(
            fetch_using(&bounded, &url).await.err(),
            Some(CheckError::Timeout)
        );
        handle.join().unwrap();
    }
}
