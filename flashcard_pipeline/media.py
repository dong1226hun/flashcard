from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote


WORKSPACE_ROOT = Path.cwd().resolve()
MEDIA_ROOT = Path("data") / "media"
PDF_MEDIA_ROOT = MEDIA_ROOT / "pdf"
GENERATED_MEDIA_ROOT = MEDIA_ROOT / "generated"
COMPOSITE_MEDIA_ROOT = GENERATED_MEDIA_ROOT / "composites"


def workspace_relative_path(path: str | Path) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(WORKSPACE_ROOT)
        except ValueError as error:
            raise ValueError(f"Path is outside workspace: {path}") from error
    return candidate.as_posix()


def media_file_path(path: str | Path) -> str:
    relative = workspace_relative_path(path)
    if relative == MEDIA_ROOT.as_posix() or relative.startswith(f"{MEDIA_ROOT.as_posix()}/"):
        return relative
    raise ValueError(f"Media path must be under {MEDIA_ROOT.as_posix()}: {path}")


def media_url(file_path: str | Path) -> str:
    relative = media_file_path(file_path)
    suffix = relative.removeprefix(MEDIA_ROOT.as_posix()).lstrip("/")
    return f"/media/{suffix}"


def static_media_url(file_path: str | Path) -> str:
    return media_url(file_path).lstrip("/")


def safe_media_path(relative_path: str) -> Path | None:
    clean_path = unquote(relative_path).replace("\\", "/").lstrip("/")
    if clean_path.startswith("media/"):
        clean_path = clean_path.removeprefix("media/")
    candidate = (WORKSPACE_ROOT / MEDIA_ROOT / clean_path).resolve()
    try:
        candidate.relative_to((WORKSPACE_ROOT / MEDIA_ROOT).resolve())
    except ValueError:
        return None
    return candidate
