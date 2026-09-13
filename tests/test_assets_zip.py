import io
import zipfile
from pathlib import Path

import pytest

from dictation.assets import _safe_extract, engine_ready


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
