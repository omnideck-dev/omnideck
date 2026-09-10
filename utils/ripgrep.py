"""Pinned ripgrep installation shared by development, CI, and the app image."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import tarfile
import tempfile
from typing import Any
from urllib.request import urlopen

_ROOT = Path(__file__).resolve().parents[1]


def _installation() -> tuple[Path, dict[str, Any]]:
    manifest = json.loads((_ROOT / 'config/ripgrep.json').read_text())
    machine = platform.machine().lower()
    machine = {'arm64': 'aarch64', 'amd64': 'x86_64'}.get(machine, machine)
    target = f'{platform.system().lower()}-{machine}'
    if target not in manifest['artifacts']:
        raise OSError(f'Pinned ripgrep is not available for {target}. Use the application container.')
    return _ROOT / '.cache/bin/ripgrep' / manifest['version'] / target, manifest['artifacts'][target]


def _verified(path: Path, digest: str) -> bool:
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest


def executable_path() -> str:
    """Return only the verified, project-owned binary; never search PATH."""
    directory, artifact = _installation()
    binary = directory / 'rg'
    if not _verified(binary, artifact['binary_sha256']) or not os.access(binary, os.X_OK):
        raise OSError('Pinned ripgrep is missing or invalid. Run `just setup-ripgrep` in this checkout, or rebuild the application image.')
    return str(binary)


def install() -> Path:
    """Download the pinned official archive, verify it, and install atomically."""
    directory, artifact = _installation()
    binary = directory / 'rg'
    if _verified(binary, artifact['binary_sha256']) and os.access(binary, os.X_OK):
        return binary
    with urlopen(artifact['url'], timeout=30) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != artifact['sha256']:
        raise ValueError('Ripgrep archive checksum mismatch; nothing installed.')
    directory.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        # Read named regular files only; never extract archive paths or links.
        for name in ('COPYING', 'LICENSE-MIT', 'UNLICENSE', 'rg'):
            member = archive.getmember(f"{artifact['prefix']}/{name}")
            if not member.isfile():
                raise ValueError(f'Expected a regular file in ripgrep archive: {name}')
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f'Missing archive content: {name}')
            content = source.read()
            if name == 'rg' and hashlib.sha256(content).hexdigest() != artifact['binary_sha256']:
                raise ValueError('Ripgrep executable checksum mismatch; executable not installed.')
            pending: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
                    pending = Path(stream.name)
                    stream.write(content)
                pending.chmod(0o755 if name == 'rg' else 0o644)
                pending.replace(directory / name)
            finally:
                if pending is not None:
                    pending.unlink(missing_ok=True)
    return binary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify without downloading.')
    args = parser.parse_args()
    try:
        print(executable_path() if args.check else install())
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')
