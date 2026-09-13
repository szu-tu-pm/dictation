from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import urllib.request
import zipfile

from dictation.config import AppConfig
from dictation.logutil import LOG
from dictation.paths import engine_dir, models_dir

ProgressCb = Callable[[str, int, int], None]

_UA = {"User-Agent": "Dictation/0.1 (Windows; local whisper.cpp)"}


def download_file(url: str, dest: Path, progress: ProgressCb | None, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            got += len(chunk)
            if progress:
                progress(label, got, total)
    tmp.replace(dest)


def _safe_extract(zip_path: Path, dest: Path) -> None:
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            target = (dest / info.filename).resolve()
            try:
                target.relative_to(dest)
            except ValueError as exc:
                raise ValueError(f"refusing zip path {info.filename!r}") from exc
        zf.extractall(dest)


def engine_ready(root: Path) -> bool:
    return (root / "whisper.dll").is_file() and (root / "whisper-cli.exe").is_file()


def ensure_engine(cfg: AppConfig, progress: ProgressCb | None = None) -> Path:
    root = engine_dir()
    if engine_ready(root):
        return root
    zip_path = root / "whisper-vulkan-win-x64.zip"
    LOG.info("Downloading whisper.cpp Vulkan engine")
    download_file(cfg.engine_url, zip_path, progress, "engine")
    _safe_extract(zip_path, root)
    try:
        zip_path.unlink(missing_ok=True)
    except OSError:
        pass
    if not engine_ready(root):
        raise FileNotFoundError(f"engine extract missing whisper.dll in {root}")
    return root


def ensure_model(cfg: AppConfig, progress: ProgressCb | None = None) -> Path:
    path = models_dir() / cfg.model_filename
    if path.is_file() and path.stat().st_size > 100_000_000:
        return path
    LOG.info("Downloading model %s", cfg.model_filename)
    download_file(cfg.model_url, path, progress, "model")
    if path.stat().st_size < 100_000_000:
        path.unlink(missing_ok=True)
        raise RuntimeError("model download looks truncated; try again")
    return path
