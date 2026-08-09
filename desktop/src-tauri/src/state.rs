use crate::{platform, BridgeError, BridgeResult};
use serde::{Deserialize, Serialize};
use std::{fs, net::TcpListener, path::Path};

pub(crate) const APP_VERSION: &str = "0.1.0-alpha.10";
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

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ImageManifest {
    schema_version: u32,
    app_version: String,
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
    if !force_new {
        if let Some(port) = persisted_port() {
            return Ok(port);
        }
    }
    let listener = TcpListener::bind(("127.0.0.1", DEFAULT_APP_PORT))
        .or_else(|_| TcpListener::bind(("127.0.0.1", 0)))
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

fn write_atomic(destination: &Path, contents: &[u8]) -> BridgeResult<()> {
    fs::create_dir_all(destination.parent().expect("state path has a parent"))
        .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))?;
    let temporary = destination.with_extension(format!("{}.partial", std::process::id()));
    fs::write(&temporary, contents)
        .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))?;

    match fs::rename(&temporary, destination) {
        Ok(()) => Ok(()),
        Err(_) if destination.exists() => {
            fs::remove_file(destination)
                .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))?;
            fs::rename(temporary, destination)
                .map_err(|error| BridgeError::new("STATE_WRITE_FAILED", error.to_string()))
        }
        Err(error) => Err(BridgeError::new("STATE_WRITE_FAILED", error.to_string())),
    }
}
