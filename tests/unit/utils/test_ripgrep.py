"""Pinned binary integrity, installation, and platform resolution contracts."""

import hashlib
import io
import json
import tarfile

import pytest

from utils import ripgrep


@pytest.fixture
def package(tmp_path, monkeypatch):
    content = b'#!/bin/sh\necho ripgrep-test\n'
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for name in ('rg', 'COPYING', 'LICENSE-MIT', 'UNLICENSE'):
            body = content if name == 'rg' else b'license notice'
            member = tarfile.TarInfo('release/' + name)
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
    raw = data.getvalue()
    artifact = dict(url='https://example.invalid/rg.tar.gz', sha256=hashlib.sha256(raw).hexdigest(),
                    binary_sha256=hashlib.sha256(content).hexdigest(), prefix='release')
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/ripgrep.json').write_text(json.dumps(dict(version='test', artifacts={'linux-aarch64': artifact})))
    monkeypatch.setattr(ripgrep, '_ROOT', tmp_path)
    monkeypatch.setattr(ripgrep.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(ripgrep.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(ripgrep, 'urlopen', lambda *a, **k: io.BytesIO(raw))
    return tmp_path


def test_install_verified_binary_and_licenses_without_path_or_cwd_dependency(package, monkeypatch):
    binary = ripgrep.install()
    monkeypatch.chdir('/')
    monkeypatch.setenv('PATH', '/nonexistent')
    assert ripgrep.executable_path() == str(binary)
    assert binary == package / '.cache/bin/ripgrep/test/linux-aarch64/rg'
    assert binary.stat().st_mode & 0o111
    assert (binary.parent / 'LICENSE-MIT').read_text() == 'license notice'
    # An existing verified installation needs no network access.
    monkeypatch.setattr(ripgrep, 'urlopen', lambda *a, **k: pytest.fail('unexpected download'))
    assert ripgrep.install() == binary


def test_missing_or_corrupt_binary_never_falls_back_to_path(package):
    with pytest.raises(OSError, match='setup-ripgrep'):
        ripgrep.executable_path()
    binary = ripgrep.install()
    binary.write_text('corrupt')
    with pytest.raises(OSError, match='setup-ripgrep'):
        ripgrep.executable_path()
    assert ripgrep.install() == binary
    assert ripgrep.executable_path() == str(binary)


def test_bad_download_does_not_install(package, monkeypatch):
    monkeypatch.setattr(ripgrep, 'urlopen', lambda *a, **k: io.BytesIO(b'wrong archive'))
    with pytest.raises(ValueError, match='checksum mismatch'):
        ripgrep.install()
    assert not (package / '.cache').exists()


def test_unsupported_platform_fails_explicitly(package, monkeypatch):
    monkeypatch.setattr(ripgrep.platform, 'machine', lambda: 'unsupported')
    with pytest.raises(OSError, match='linux-unsupported'):
        ripgrep.executable_path()
