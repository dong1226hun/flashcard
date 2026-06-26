from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import DEFAULT_DB_PATH, connect, init_db
from .media import static_media_url
from .study import available_cards, study_sections


ROOT = Path.cwd()
PACKAGE_DIR = Path(__file__).parent
STATIC_DIR = PACKAGE_DIR / "static"
DEFAULT_OUTPUT_DIR = Path("docs")


def convert_card_paths(card: dict[str, Any]) -> dict[str, Any]:
    card = dict(card)
    media = []
    for item in card.get("media", []):
        item = dict(item)
        if item.get("file_path"):
            item["src"] = static_media_url(item["file_path"])
            item.pop("file_path", None)
        media.append(item)
    card["media"] = media
    return card


def referenced_asset_paths(cards: list[dict[str, Any]]) -> set[str]:
    paths: set[str] = set()
    for card in cards:
        for item in card.get("media", []):
            if item.get("file_path"):
                paths.add(str(item["file_path"]))
    return paths


def resolve_workspace_path(relative_path: str) -> Path:
    source = Path(relative_path)
    if not source.is_absolute():
        source = ROOT / source
    resolved = source.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as error:
        raise ValueError(f"Refusing to export path outside workspace: {relative_path}") from error
    return resolved


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_index(output_dir: Path) -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = re.sub(r'href="/static/styles/study\.css(\?[^"]*)?"', r'href="./static/styles/study.css\1"', html)
    html = re.sub(r'src="/static/study/main\.js(\?[^"]*)?"', r'src="./static/study/main.js\1"', html)
    html = html.replace('data-provider="api"', 'data-provider="static"')
    (output_dir / "index.html").write_text(html, encoding="utf-8")


def copytree_replace(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def copy_static(output_dir: Path) -> None:
    static_dir = output_dir / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    for legacy_file in (static_dir / "exam.css", static_dir / "styles.css", static_dir / "exam.js"):
        if legacy_file.exists():
            legacy_file.unlink()
    copytree_replace(STATIC_DIR / "styles", static_dir / "styles")
    copytree_replace(STATIC_DIR / "fonts", static_dir / "fonts")
    copytree_replace(STATIC_DIR / "study", static_dir / "study")


def copy_assets(output_dir: Path, asset_paths: set[str]) -> tuple[int, int]:
    copied = 0
    skipped = 0
    for relative_path in sorted(asset_paths):
        source = resolve_workspace_path(relative_path)
        destination = output_dir / static_media_url(relative_path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"Missing asset: {relative_path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.stat().st_size == source.stat().st_size:
            skipped += 1
            continue
        shutil.copy2(source, destination)
        copied += 1
    return copied, skipped


def clean_output_dir(output_dir: Path) -> None:
    resolved = output_dir.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as error:
        raise ValueError(f"Refusing to clean outside workspace: {output_dir}") from error
    if resolved == ROOT.resolve():
        raise ValueError("Refusing to clean workspace root")
    if output_dir.exists():
        shutil.rmtree(output_dir)


def export_pages(db_path: Path, output_dir: Path, *, clean: bool = False) -> dict[str, Any]:
    if clean:
        clean_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")

    conn = connect(db_path)
    try:
        init_db(conn)
        raw_cards = available_cards(conn, include_file_path=True)
        sections = study_sections(conn)
    finally:
        conn.close()

    asset_paths = referenced_asset_paths(raw_cards)
    cards = [convert_card_paths(card) for card in raw_cards]
    generated_at = datetime.now(timezone.utc).isoformat()
    card_payload = {
        "generated_at": generated_at,
        "card_count": len(cards),
        "cards": cards,
    }
    sections_payload = {
        "generated_at": generated_at,
        **sections,
    }

    write_json(output_dir / "data" / "cards.json", card_payload)
    write_json(output_dir / "data" / "sections.json", sections_payload)
    write_index(output_dir)
    copy_static(output_dir)
    copied, skipped = copy_assets(output_dir, asset_paths)

    return {
        "output_dir": str(output_dir),
        "cards": len(cards),
        "assets_copied": copied,
        "assets_skipped": skipped,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export the study UI as a GitHub Pages static site.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="GitHub Pages output directory")
    parser.add_argument("--clean", action="store_true", help="Delete the output directory before exporting")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = export_pages(args.db, args.output, clean=args.clean)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
