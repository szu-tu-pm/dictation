import hashlib
import io
from pathlib import Path
from unittest.mock import MagicMock, patch
import zipfile

import pytest

from dictation.assets import (
    _safe_extract,
    download_file,
    engine_ready,
    ensure_engine,
    ensure_model,
    sha256_file,
    verify_sha256,
)
from dictation.config import AppConfig


def _zip_bytes(names_to_data: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in names_to_data.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_safe_extract_ok(tmp_path: Path) -> None:
    archive = tmp_path / "ok.zip"
    archive.write_bytes(_zip_bytes({"whisper.dll": b"x", "nested/a.txt": b"y"}))
    dest = tmp_path / "out"
    _safe_extract(archive, dest)
    assert (dest / "whisper.dll").read_bytes() == b"x"
    assert (dest / "nested" / "a.txt").read_bytes() == b"y"


def test_safe_extract_rejects_zip_slip(tmp_path: Path) -> None:
    dest = tmp_path / "out"
    dest.mkdir()
    for name in ("../evil.txt", "..\\evil.txt"):
        archive = tmp_path / "bad.zip"
        archive.write_bytes(_zip_bytes({name: b"nope"}))
        with pytest.raises(ValueError, match="refusing zip path"):
            _safe_extract(archive, dest)
    assert not (tmp_path / "evil.txt").exists()


def test_engine_ready_requires_both_files(tmp_path: Path) -> None:
    assert not engine_ready(tmp_path)
    (tmp_path / "whisper.dll").write_bytes(b"x")
    assert not engine_ready(tmp_path)
    (tmp_path / "whisper-cli.exe").write_bytes(b"x")
    assert engine_ready(tmp_path)


def test_sha256_file_and_verify(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    data = b"hello-dictation"
    path.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    assert sha256_file(path) == expected
    verify_sha256(path, expected)
    verify_sha256(path, expected.upper())
    verify_sha256(path, "")  # empty expected skips
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        verify_sha256(path, "0" * 64)


class _FakeResp:
    def __init__(self, payload: bytes, *, content_length: bool = True) -> None:
        self._buf = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))} if content_length else {}

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_download_file_writes_via_part_then_rename(tmp_path: Path) -> None:
    dest = tmp_path / "model.bin"
    payload = b"abc" * 1000
    progress = MagicMock()
    expected = hashlib.sha256(payload).hexdigest()

    with patch("dictation.assets.urllib.request.urlopen", return_value=_FakeResp(payload)):
        got = download_file("https://example.test/model.bin", dest, progress, "model")

    assert got == expected
    assert dest.read_bytes() == payload
    assert not dest.with_suffix(dest.suffix + ".part").exists()
    assert progress.called


def test_download_file_streams_and_rejects_bad_checksum(tmp_path: Path) -> None:
    dest = tmp_path / "model.bin"
    payload = b"abc" * 1000
    part = dest.with_suffix(dest.suffix + ".part")

    with patch("dictation.assets.urllib.request.urlopen", return_value=_FakeResp(payload)):
        with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
            download_file(
                "https://example.test/model.bin",
                dest,
                None,
                "model",
                expected_sha256="0" * 64,
            )

    assert not dest.exists()
    assert not part.exists()


def test_download_file_cleans_part_on_failure(tmp_path: Path) -> None:
    dest = tmp_path / "model.bin"
    part = dest.with_suffix(dest.suffix + ".part")

    class _BoomResp(_FakeResp):
        def read(self, n: int = -1) -> bytes:
            raise OSError("network dropped")

    with patch("dictation.assets.urllib.request.urlopen", return_value=_BoomResp(b"partial")):
        with pytest.raises(OSError, match="network dropped"):
            download_file("https://example.test/model.bin", dest, None, "model")

    assert not dest.exists()
    assert not part.exists()


def test_ensure_engine_rejects_bad_checksum(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    cfg = AppConfig(engine_sha256="a" * 64)

    with patch(
        "dictation.assets.download_file",
        side_effect=RuntimeError("SHA-256 mismatch for whisper-vulkan-win-x64.zip"),
    ):
        with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
            ensure_engine(cfg)
    zip_path = tmp_path / "Dictation" / "engine" / "whisper-vulkan-win-x64.zip"
    assert not zip_path.exists()
    assert not engine_ready(tmp_path / "Dictation" / "engine")


def test_ensure_engine_extracts_when_checksum_ok(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    zip_bytes = _zip_bytes({"whisper.dll": b"x", "whisper-cli.exe": b"y"})
    digest = hashlib.sha256(zip_bytes).hexdigest()
    cfg = AppConfig(engine_sha256=digest)

    with patch("dictation.assets.download_file") as mock_dl:

        def _fake_dl(
            url: str,
            dest: Path,
            progress,
            label: str,
            *,
            expected_sha256: str = "",
        ) -> str:
            assert expected_sha256 == digest
            dest.write_bytes(zip_bytes)
            return digest

        mock_dl.side_effect = _fake_dl
        root = ensure_engine(cfg)

    assert engine_ready(root)
    assert not (root / "whisper-vulkan-win-x64.zip").exists()


def test_ensure_model_rejects_bad_checksum(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    cfg = AppConfig(model_sha256="b" * 64, model_filename="ggml-test.bin")

    with patch(
        "dictation.assets.download_file",
        side_effect=RuntimeError("SHA-256 mismatch for ggml-test.bin"),
    ):
        with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
            ensure_model(cfg)

    path = tmp_path / "Dictation" / "models" / "ggml-test.bin"
    assert not path.exists()
