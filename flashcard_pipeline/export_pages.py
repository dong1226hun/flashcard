from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .caption_labels import FIGURE_TAG_RE
from .db import DEFAULT_DB_PATH, connect, init_db
from .study import available_cards, study_sections


ROOT = Path.cwd()
PACKAGE_DIR = Path(__file__).parent
STATIC_DIR = PACKAGE_DIR / "static"
DEFAULT_OUTPUT_DIR = Path("docs")


def relative_url(path: str) -> str:
    return Path(path).as_posix()


def figure_label(caption: str) -> str:
    match = FIGURE_TAG_RE.search(caption or "")
    if not match:
        return ""
    label = match.group("label") or ""
    return f"Fig. {match.group('chapter')}-{match.group('figure')}{label}."


def convert_card_paths(card: dict[str, Any]) -> dict[str, Any]:
    card = dict(card)
    card["figure_label"] = figure_label(card.get("caption_text", ""))
    if card.get("file_path"):
        card["image_url"] = relative_url(card["file_path"])
    images = []
    for image in card.get("images", []):
        image = dict(image)
        if image.get("file_path"):
            image["image_url"] = relative_url(image["file_path"])
        images.append(image)
    card["images"] = images
    return card


def referenced_asset_paths(cards: list[dict[str, Any]]) -> set[str]:
    paths: set[str] = set()
    for card in cards:
        if card.get("file_path"):
            paths.add(str(card["file_path"]))
        for image in card.get("images", []):
            if image.get("file_path"):
                paths.add(str(image["file_path"]))
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
    html = re.sub(r'href="/static/exam\.css(?:\?v=\d+)?"', 'href="./static/exam.css"', html)
    html = re.sub(r'src="/static/exam\.js(?:\?v=\d+)?"', 'src="./static/exam.js"', html)
    (output_dir / "index.html").write_text(html, encoding="utf-8")


def copy_static(output_dir: Path) -> None:
    static_dir = output_dir / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(STATIC_DIR / "exam.css", static_dir / "exam.css")
    shutil.copy2(STATIC_DIR / "pages_exam.js", static_dir / "exam.js")


def copy_assets(output_dir: Path, asset_paths: set[str]) -> tuple[int, int]:
    copied = 0
    skipped = 0
    for relative_path in sorted(asset_paths):
        source = resolve_workspace_path(relative_path)
        destination = output_dir / relative_url(relative_path)
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
        raw_cards = available_cards(conn)
        sections = study_sections(conn)
    finally:
        conn.close()

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
    copied, skipped = copy_assets(output_dir, referenced_asset_paths(cards))

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
