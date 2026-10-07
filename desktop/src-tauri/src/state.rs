use crate::{platform, BridgeError, BridgeResult};
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    net::TcpListener,
    path::Path,
    sync::atomic::{AtomicU64, Ordering},
};

pub(crate) const APP_VERSION: &str = "0.1.0-beta.13";
const DEFAULT_APP_PORT: u16 = 2338;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SetupRecord {
    schema_version: u32,
    pub(crate) status: String,
    pub(crate) reason: String,
    pub(crate) app_version: String,
    pub(crate) image_version: String,
    pub(crate) image_ref: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SetupRecordWrite<'a> {
    schema_version: u32,
    status: &'a str,
    reason: &'a str,
    app_version: &'a str,
    image_version: &'a str,
    image_ref: &'a str,
    image_digest: &'a str,
    updated_at: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ImageManifest {
    pub(crate) schema_version: u32,
    pub(crate) app_version: String,
    pub(crate) image_version: String,
    pub(crate) image_ref: String,
}

pub(crate) fn read_setup_record() -> Option<SetupRecord> {
    let path = platform::user_data_dir().ok()?.join("setup-state.json");
    let record: SetupRecord = serde_json::from_slice(&fs::read(path).ok()?).ok()?;
    if record.schema_version != 2
        || !matches!(record.status.as_str(), "in-progress" | "complete")
        || !matches!(
            record.reason.as_str(),
            "first-run" | "resume" | "update" | "repair"
        )
        || record.app_version.is_empty()
        || record.image_version.is_empty()
        || record.image_ref.is_empty()
    {
        return None;
    }
    Some(record)
}

pub(crate) fn persisted_port() -> Option<u16> {
    let raw = fs::read_to_string(platform::user_data_dir().ok()?.join("runtime/app-port")).ok()?;
    raw.trim().parse().ok().filter(|port| *port > 0)
}

pub(crate) fn reserve_and_persist_port(force_new: bool) -> BridgeResult<u16> {
    let previous = persisted_port();
    if !force_new {
        if let Some(port) = previous {
            return Ok(port);
        }
    }
    let listener = select_port(force_new, previous)
        .map_err(|error| BridgeError::new("PORT_UNAVAILABLE", error.to_string()))?;
    let port = listener
        .local_addr()
        .map_err(|error| BridgeError::new("PORT_UNAVAILABLE", error.to_string()))?
        .port();
    drop(listener);
    let path = platform::user_data_dir()?.join("runtime/app-port");
    write_atomic(&path, format!("{port}\n").as_bytes())?;
    Ok(port)
}

fn select_port(force_new: bool, previous: Option<u16>) -> std::io::Result<TcpListener> {
    if !force_new {
        if let Ok(listener) = TcpListener::bind(("127.0.0.1", DEFAULT_APP_PORT)) {
            return Ok(listener);
        }
    }
    // A stopped CLI instance can reserve a port without listening on it. A
    // retry must not select that rejected port just because bind succeeds.
    loop {
        let listener = TcpListener::bind(("127.0.0.1", 0))?;
        if Some(listener.local_addr()?.port()) != previous {
            return Ok(listener);
        }
        // Keep the rejected address bound until the second allocation so the
        // OS cannot repeatedly return it from its ephemeral range.
        let replacement = TcpListener::bind(("127.0.0.1", 0))?;
        if Some(replacement.local_addr()?.port()) != previous {
            return Ok(replacement);
        }
    }
}

pub(crate) fn image_manifest() -> BridgeResult<ImageManifest> {
    let manifest: ImageManifest =
        serde_json::from_str(include_str!("../resources/image-manifest.json"))
            .map_err(|error| BridgeError::new("INVALID_IMAGE_MANIFEST", error.to_string()))?;
    let valid_ref = manifest.image_ref.starts_with("ghcr.io/")
        && manifest.image_ref.contains("@sha256:")
        && manifest
            .image_ref
            .rsplit("@sha256:")
            .next()
            .is_some_and(|digest| {
                digest.len() == 64 && digest.bytes().all(|byte| byte.is_ascii_hexdigit())
            });
    if manifest.schema_version != 3
        || manifest.app_version != APP_VERSION
        || manifest.image_version.is_empty()
        || !valid_ref
    {
        return Err(BridgeError::new(
            "INVALID_IMAGE_MANIFEST",
            "The omnideck runtime image does not match this application release.",
        ));
    }
    Ok(manifest)
}

pub(crate) fn save_setup_record(
    status: &str,
    reason: &str,
    manifest: &ImageManifest,
) -> BridgeResult<()> {
    let digest = manifest.image_ref.rsplit('@').next().unwrap_or("");
    let record = SetupRecordWrite {
        schema_version: 2,
        status,
        reason,
        app_version: APP_VERSION,
        image_version: &manifest.image_version,
        image_ref: &manifest.image_ref,
        image_digest: digest,
        updated_at: time::OffsetDateTime::now_utc()
            .format(&time::format_description::well_known::Rfc3339)
            .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))?,
    };
    let mut encoded = serde_json::to_vec_pretty(&record)
        .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))?;
    encoded.push(b'\n');
    write_atomic(
        &platform::user_data_dir()?.join("setup-state.json"),
        &encoded,
    )
}

pub(crate) fn write_atomic(destination: &Path, contents: &[u8]) -> BridgeResult<()> {
    static NEXT_TEMPORARY: AtomicU64 = AtomicU64::new(0);
    let result = (|| -> std::io::Result<()> {
        fs::create_dir_all(destination.parent().expect("state path has a parent"))?;
        let (temporary, mut file) = loop {
            let sequence = NEXT_TEMPORARY.fetch_add(1, Ordering::Relaxed);
            let temporary =
                destination.with_extension(format!("{}.{sequence}.partial", std::process::id()));
            match OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temporary)
            {
                Ok(file) => break (temporary, file),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => return Err(error),
            }
        };
        let written = file.write_all(contents).and_then(|_| file.sync_all());
        drop(file);
        // std::fs::rename atomically replaces files on all supported targets.
        // Never delete the last good destination after an arbitrary failure.
        let replaced = written.and_then(|_| fs::rename(&temporary, destination));
        if replaced.is_err() {
            let _ = fs::remove_file(&temporary);
        }
        replaced
    })();
    result.map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_directory(name: &str) -> std::path::PathBuf {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("target/test-artifacts")
            .join(format!(
                "omnideck-state-{}-{name}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
        fs::create_dir_all(&path).unwrap();
        path
    }

    #[test]
    fn retry_never_reuses_the_rejected_port() {
        let initial = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let rejected = initial.local_addr().unwrap().port();
        drop(initial);
        assert_ne!(
            select_port(true, Some(rejected))
                .unwrap()
                .local_addr()
                .unwrap()
                .port(),
            rejected
        );
        assert_ne!(
            select_port(true, Some(DEFAULT_APP_PORT))
                .unwrap()
                .local_addr()
                .unwrap()
                .port(),
            DEFAULT_APP_PORT
        );
    }

    #[test]
    fn concurrent_atomic_writes_leave_one_complete_document() {
        let directory = test_directory("concurrent");
        let destination = directory.join("state.json");
        std::thread::scope(|scope| {
            for value in 0..16 {
                let destination = &destination;
                scope.spawn(move || {
                    let body =
                        format!("{{\"value\":{value},\"padding\":\"{}\"}}", "x".repeat(8192));
                    write_atomic(destination, body.as_bytes()).unwrap();
                });
            }
        });
        let value: serde_json::Value =
            serde_json::from_slice(&fs::read(&destination).unwrap()).unwrap();
        assert_eq!(value["padding"].as_str().unwrap().len(), 8192);
        assert_eq!(fs::read_dir(&directory).unwrap().count(), 1);
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn failed_replacement_preserves_existing_destination() {
        let directory = test_directory("failure");
        let destination = directory.join("state.json");
        fs::create_dir(&destination).unwrap();
        fs::write(destination.join("sentinel"), b"keep").unwrap();
        assert!(write_atomic(&destination, b"replacement").is_err());
        assert_eq!(fs::read(destination.join("sentinel")).unwrap(), b"keep");
        assert_eq!(fs::read_dir(&directory).unwrap().count(), 1);
        fs::remove_dir_all(directory).unwrap();
    }
}
