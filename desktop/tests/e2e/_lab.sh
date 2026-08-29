#!/usr/bin/env bash

require_lab() {
  lab_dir="${OMNIDECK_VM_LAB_DIR:-}"
  [[ -n "$lab_dir" ]] || { printf 'Set OMNIDECK_VM_LAB_DIR to the external VM lab root.\n' >&2; exit 2; }
  [[ -x "$lab_dir/lab.sh" ]] || { printf 'Missing executable lab.sh under %s\n' "$lab_dir" >&2; exit 2; }
  lab_dir="$(cd "$lab_dir" && pwd -P)"
  python3 -c 'import json,subprocess,sys; data=json.loads(subprocess.check_output([sys.argv[1], "capabilities", "--json"])); required={"artifact-path","cache-path","lease-cleanup","preflight","profiles"}; missing=required-set(data["features"]); assert not missing, f"VM lab lacks: {sorted(missing)}"' "$lab_dir/lab.sh" || {
    printf 'Desktop VM E2E requires the OmniDeck VM lab 2.1 capability contract.\n' >&2
    exit 2
  }
}

desktop_source_state() {
  source_full_commit="$(git -C "$repo_root" rev-parse HEAD)"
  source_commit="${source_full_commit:0:12}"
  source_dirty=false
  [[ -z "$(git -C "$repo_root" status --porcelain=v1 --untracked-files=normal)" ]] || source_dirty=true
  source_fingerprint="$({
    git -C "$repo_root" diff --binary HEAD --
    while IFS= read -r file; do (cd "$repo_root" && sha256sum "$file"); done < <(git -C "$repo_root" ls-files --others --exclude-standard | sort)
  } | sha256sum | awk '{print substr($1,1,20)}')"
}

ensure_desktop_builder() {
  local target="$1" dockerfile key
  dockerfile="$desktop_root/containers/${target}-builder/Dockerfile"
  key="$(sha256sum "$dockerfile" "$desktop_root/pnpm-lock.yaml" | awk '{print $1}' | sha256sum | awk '{print substr($1,1,20)}')"
  desktop_builder_image="omnideck-desktop-${target}-builder:${key}"
  if ! docker image inspect "$desktop_builder_image" >/dev/null 2>&1; then
    docker build --tag "$desktop_builder_image" --file "$dockerfile" "$repo_root"
  fi
  desktop_builder_id="$(docker image inspect "$desktop_builder_image" --format '{{.Id}}')"
}

ensure_cli_builder() {
  local dockerfile key
  dockerfile="$cli_root/.devcontainer/Dockerfile"
  [[ -f "$dockerfile" ]] || { printf 'CLI builder Dockerfile not found: %s\n' "$dockerfile" >&2; exit 2; }
  key="$(sha256sum "$dockerfile" "$cli_root/go.mod" "$cli_root/go.sum" | awk '{print $1}' | sha256sum | awk '{print substr($1,1,20)}')"
  cli_builder_image="omnideck-cli-builder:${key}"
  if ! docker image inspect "$cli_builder_image" >/dev/null 2>&1; then
    docker build --tag "$cli_builder_image" --file "$dockerfile" "$cli_root/.devcontainer"
  fi
}

prepare_tauri_driver() {
  local target="$1" key cache_dir temporary binary
  ensure_desktop_builder "$target"
  key="tauri-driver-2.0.6-${target}-$(printf '%s' "$desktop_builder_id" | sha256sum | awk '{print substr($1,1,20)}')"
  cache_dir="$("$lab_dir/lab.sh" cache-path desktop "$key")"
  mkdir -p "$(dirname "$cache_dir")"
  if [[ "$target" == windows ]]; then binary=tauri-driver.exe; else binary=tauri-driver; fi
  if [[ ! -f "$cache_dir/$binary" ]]; then
    temporary="$(mktemp -d "$lab_dir/cache/desktop/.${key}.XXXXXX")"
    target_args=()
    [[ "$target" != windows ]] || target_args=(--target x86_64-pc-windows-gnu)
    docker run --rm --user "$(id -u):$(id -g)" \
      --env HOME=/tmp/omnideck-driver-home --env CARGO_HOME=/tmp/omnideck-driver-cargo \
      --env RUSTUP_HOME=/usr/local/rustup --volume "$temporary:/out" "$desktop_builder_image" \
      bash -c "mkdir -p \"\$HOME\" \"\$CARGO_HOME\" && cargo install tauri-driver --version 2.0.6 --locked ${target_args[*]} --root /out/root"
    mv "$temporary/root/bin/$binary" "$temporary/$binary"
    find "$temporary/root" -type f -delete
    find "$temporary/root" -depth -type d -empty -delete
    printf '%s\n' "$desktop_builder_id" > "$temporary/builder-image.txt"
    : > "$temporary/.complete"
    if ! mv -T -- "$temporary" "$cache_dir" 2>/dev/null; then
      find "$temporary" -type f -delete
      find "$temporary" -depth -type d -empty -delete
    fi
  fi
  tauri_driver_cache="$cache_dir"
  tauri_driver_key="$key"
  touch "$cache_dir"
}

write_desktop_source_metadata() {
  python3 - "$output_dir/source.json" "$source_full_commit" "$source_dirty" "$source_fingerprint" "$desktop_builder_id" <<'PY'
import json, sys
path, commit, dirty, fingerprint, builder = sys.argv[1:]
with open(path, "w") as handle:
    json.dump({"schemaVersion": 1, "sourceCommit": commit, "sourceDirty": dirty == "true", "sourceFingerprint": fingerprint, "builderImage": builder}, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
}

cache_candidate_artifact() {
  local requested="$1" kind="$2" digest key cache_dir temporary original_name
  requested="$(realpath -e "$requested")"
  original_name="$(basename "$requested")"
  if [[ -f "$(dirname "$requested")/original-filename.txt" ]]; then
    original_name="$(<"$(dirname "$requested")/original-filename.txt")"
  fi
  digest="$(sha256sum "$requested" | awk '{print $1}')"
  key="candidate-${kind}-${digest:0:20}"
  cache_dir="$("$lab_dir/lab.sh" cache-path desktop "$key")"
  mkdir -p "$(dirname "$cache_dir")"
  if [[ ! -f "$cache_dir/artifact" ]]; then
    temporary="$(mktemp -d "$lab_dir/cache/desktop/.${key}.XXXXXX")"
    cp -- "$requested" "$temporary/artifact"
    printf '%s  artifact\n' "$digest" > "$temporary/SHA256SUMS"
    printf '%s\n' "$original_name" > "$temporary/original-filename.txt"
    : > "$temporary/.complete"
    if ! mv -T -- "$temporary" "$cache_dir" 2>/dev/null; then
      find "$temporary" -type f -delete
      find "$temporary" -depth -type d -empty -delete
    fi
  fi
  prepared_artifact="$cache_dir/artifact"
  prepared_artifact_key="$key"
  prepared_artifact_original_name="$original_name"
  touch "$cache_dir"
}

create_desktop_build_output() {
  local target="$1" builder_key
  builder_key="$(printf '%s' "$desktop_builder_id" | sha256sum | awk '{print substr($1,1,20)}')"
  desktop_builder_cache="$("$lab_dir/lab.sh" cache-path desktop-build "${target}-${builder_key}")"
  desktop_build_output="${desktop_builder_cache}/target"
  mkdir -p "$desktop_build_output" "${desktop_builder_cache}/home" \
    "${desktop_builder_cache}/cargo" "${desktop_builder_cache}/xdg" \
    "${desktop_builder_cache}/pnpm"
  touch "$desktop_builder_cache"
}

remove_desktop_build_output() {
  # Build output is a reusable Cargo target cache keyed by builder image. Cargo
  # fingerprints source inputs, while the lab GC owns cache retention.
  desktop_build_output=""
  desktop_builder_cache=""
}
