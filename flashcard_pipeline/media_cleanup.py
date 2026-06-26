from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from .db import DEFAULT_DB_PATH, connect, init_db
from .media import MEDIA_ROOT, WORKSPACE_ROOT, media_file_path, workspace_relative_path


LEGACY_PREFIXES = (
    ("assets/raw/pdf/", "data/media/pdf/"),
    ("assets/pdf/", "data/media/pdf/"),
    ("assets/generated/composites/", "data/media/generated/composites/"),
)

LEGACY_DIRS = (
    Path("assets") / "pdf",
    Path("assets") / "raw",
    Path("docs") / "assets",
)


def ensure_workspace_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError as error:
        raise ValueError(f"Refusing to touch path outside workspace: {path}") from error
    return resolved


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def migrated_path(file_path: str) -> str:
    relative = workspace_relative_path(file_path).replace("\\", "/")
    if relative == MEDIA_ROOT.as_posix() or relative.startswith(f"{MEDIA_ROOT.as_posix()}/"):
        return media_file_path(relative)
    for old_prefix, new_prefix in LEGACY_PREFIXES:
        if relative.startswith(old_prefix):
            return media_file_path(f"{new_prefix}{relative.removeprefix(old_prefix)}")
    raise ValueError(f"Unsupported media path: {file_path}")


def load_media_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, file_path
        FROM extracted_images
        ORDER BY id
        """
    ).fetchall()


def preflight_moves(moves: dict[str, str]) -> None:
    missing: list[str] = []
    conflicts: list[str] = []
    for source_rel, dest_rel in moves.items():
        if source_rel == dest_rel:
            continue
        source = ensure_workspace_path(WORKSPACE_ROOT / source_rel)
        dest = ensure_workspace_path(WORKSPACE_ROOT / dest_rel)
        if source.exists() and dest.exists():
            if source.stat().st_size != dest.stat().st_size or file_digest(source) != file_digest(dest):
                conflicts.append(f"{source_rel} -> {dest_rel}")
        elif not source.exists() and not dest.exists():
            missing.append(source_rel)
    if missing or conflicts:
        raise FileNotFoundError(
            json.dumps(
                {
                    "missing": missing,
                    "conflicts": conflicts,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


def move_files(moves: dict[str, str]) -> int:
    moved = 0
    for source_rel, dest_rel in sorted(moves.items()):
        if source_rel == dest_rel:
            continue
        source = ensure_workspace_path(WORKSPACE_ROOT / source_rel)
        dest = ensure_workspace_path(WORKSPACE_ROOT / dest_rel)
        if source.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                source.unlink()
            else:
                shutil.move(str(source), str(dest))
            moved += 1
    return moved


def update_db_paths(conn: sqlite3.Connection, updates: dict[int, str]) -> int:
    changed = 0
    with conn:
        for image_id, next_path in updates.items():
            cursor = conn.execute(
                """
                UPDATE extracted_images
                SET file_path = ?
                WHERE id = ?
                """,
                (next_path, image_id),
            )
            changed += cursor.rowcount
    return changed


def remove_legacy_dirs() -> list[str]:
    removed: list[str] = []
    for relative in LEGACY_DIRS:
        target = ensure_workspace_path(WORKSPACE_ROOT / relative)
        if target.exists():
            shutil.rmtree(target)
            removed.append(relative.as_posix())

    for relative in (
        Path("assets") / "generated" / "composites",
        Path("assets") / "generated",
        Path("assets"),
    ):
        target = ensure_workspace_path(WORKSPACE_ROOT / relative)
        if target.exists() and target.is_dir() and not any(target.iterdir()):
            target.rmdir()
            removed.append(relative.as_posix())
    return removed


def validate_media_state(conn: sqlite3.Connection) -> dict[str, int]:
    rows = load_media_rows(conn)
    missing = []
    invalid = []
    for row in rows:
        file_path = row["file_path"]
        try:
            normalized = media_file_path(file_path)
        except ValueError:
            invalid.append(file_path)
            continue
        path = ensure_workspace_path(WORKSPACE_ROOT / normalized)
        if not path.exists() or not path.is_file():
            missing.append(normalized)
    if missing or invalid:
        raise RuntimeError(
            json.dumps(
                {
                    "missing": missing,
                    "invalid": invalid,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return {
        "image_rows": len(rows),
        "distinct_files": len({row["file_path"] for row in rows}),
    }


def cleanup_media(db_path: Path = DEFAULT_DB_PATH, *, delete_legacy: bool = True) -> dict:
    backup_path = db_path.with_name(
        f"{db_path.name}.before_media_cleanup_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    shutil.copy2(db_path, backup_path)

    conn = connect(db_path)
    try:
        init_db(conn)
        rows = load_media_rows(conn)
        updates: dict[int, str] = {}
        moves: dict[str, str] = {}
        for row in rows:
            source_path = workspace_relative_path(row["file_path"]).replace("\\", "/")
            dest_path = migrated_path(source_path)
            updates[int(row["id"])] = dest_path
            moves[source_path] = dest_path

        preflight_moves(moves)
        files_moved = move_files(moves)
        rows_updated = update_db_paths(conn, updates)
        validation = validate_media_state(conn)
    finally:
        conn.close()

    removed_dirs = remove_legacy_dirs() if delete_legacy else []
    return {
        "db_path": str(db_path),
        "backup_path": str(backup_path),
        "files_moved": files_moved,
        "rows_updated": rows_updated,
        "removed_dirs": removed_dirs,
        **validation,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Move flashcard media into data/media and update DB paths.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--keep-legacy", action="store_true", help="Do not delete old assets/docs asset folders.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = cleanup_media(args.db, delete_legacy=not args.keep_legacy)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
