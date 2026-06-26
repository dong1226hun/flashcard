from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path
from typing import Iterable

from .answer_fields import answer_fields_from_caption, answer_is_caption_derived
from .db import DEFAULT_DB_PATH, connect, figure_metadata, init_db


DASHES = r"\-\u2010\u2011\u2012\u2013\u2014\u2015\uff0d"
FIGURE_TAG_RE = re.compile(
    rf"(?P<head>(?:\uadf8\ub9bc|Fig\.?|Figure)\s*"
    rf"(?P<chapter>\d+)\s*[{DASHES}]\s*(?P<figure>\d+))"
    rf"(?P<label>[A-Za-z])?",
    re.IGNORECASE,
)
PANEL_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PANEL_MARKER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<labels>[A-Z](?:\s*,\s*[A-Z])*)\s*(?P<sep>[,.])"
)


def figure_tag_keys(caption: str) -> list[str]:
    keys: list[str] = []
    for match in FIGURE_TAG_RE.finditer(caption or ""):
        key = f"{match.group('chapter')}-{match.group('figure')}"
        if key not in keys:
            keys.append(key)
    return keys


def panel_label_for(index: int) -> str:
    if index < len(PANEL_LABELS):
        return PANEL_LABELS[index]
    return f"p{index + 1}"


def marker_labels(value: str) -> set[str]:
    return {part.strip().upper() for part in value.split(",") if part.strip()}


def panel_markers(caption: str) -> list[re.Match[str]]:
    tag_match = FIGURE_TAG_RE.search(caption or "")
    start = tag_match.end() if tag_match else 0
    return list(PANEL_MARKER_RE.finditer(caption or "", start))


def prefix_is_only_figure_tag(prefix: str) -> bool:
    tag_match = FIGURE_TAG_RE.search(prefix or "")
    if not tag_match:
        return False
    return not any(char.isalnum() for char in prefix[tag_match.end() :])


def trim_to_panel_description(caption: str, label: str) -> str:
    markers = panel_markers(caption)
    if not markers:
        return caption

    target = label.upper()
    target_index = None
    for index, marker in enumerate(markers):
        if target in marker_labels(marker.group("labels")):
            target_index = index
            break
    if target_index is None:
        return caption

    first = markers[0]
    current = markers[target_index]
    next_marker = markers[target_index + 1] if target_index + 1 < len(markers) else None
    prefix = caption[: first.start()].rstrip()
    segment_body = caption[current.end() : next_marker.start() if next_marker else len(caption)]
    segment = segment_body.strip() if prefix_is_only_figure_tag(prefix) else f"{target}{current.group('sep')}{segment_body}".strip()
    return f"{prefix} {segment}".strip()


def caption_with_panel_label(caption: str, label: str) -> str:
    label = label.upper()

    def replace(match: re.Match[str]) -> str:
        return f"{match.group('head')}{label}"

    labeled = FIGURE_TAG_RE.sub(replace, caption or "", count=1)
    return trim_to_panel_description(labeled, label)


def apply_panel_labels(
    conn: sqlite3.Connection,
    *,
    document_id: str | None = None,
) -> dict:
    where = ""
    params: list[str] = []
    if document_id:
        where = "WHERE c.document_id = ?"
        params.append(document_id)

    rows = conn.execute(
        f"""
        SELECT
            c.id,
            c.document_id,
            c.caption_text,
            c.answer_text,
            c.answer_explanation,
            c.source_page,
            i.page_image_index
        FROM cards c
        JOIN card_images ci ON ci.card_id = c.id
        JOIN extracted_images i ON i.id = ci.image_id
        {where}
          {"AND" if where else "WHERE"} ci.sort_order = (
              SELECT MIN(sort_order) FROM card_images WHERE card_id = c.id
          )
        ORDER BY c.document_id, c.source_page, i.page_image_index, c.id
        """,
        params,
    ).fetchall()

    groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
    skipped_multi_tag = 0
    for row in rows:
        keys = figure_tag_keys(row["caption_text"])
        if len(keys) != 1:
            if len(keys) > 1:
                skipped_multi_tag += 1
            continue
        groups.setdefault((row["document_id"], keys[0]), []).append(row)

    updates: list[tuple[str, int, str, int, str, str, str, int, int, int]] = []
    labeled_groups = 0
    for items in groups.values():
        if len(items) <= 1:
            continue
        labeled_groups += 1
        for index, row in enumerate(items):
            next_caption = caption_with_panel_label(row["caption_text"], panel_label_for(index))
            if next_caption != row["caption_text"]:
                chapter, source_label, sort_order = figure_metadata(next_caption)
                fields = answer_fields_from_caption(next_caption)
                should_update_answer = answer_is_caption_derived(row["answer_text"], row["caption_text"])
                updates.append(
                    (
                        next_caption,
                        1 if should_update_answer else 0,
                        fields.answer_text,
                        1 if should_update_answer else 0,
                        fields.answer_explanation,
                        chapter,
                        source_label,
                        sort_order,
                        sort_order,
                        int(row["id"]),
                    )
                )

    conn.executemany(
        """
        UPDATE cards
        SET
            caption_text = ?,
            answer_text = CASE WHEN ? THEN ? ELSE answer_text END,
            answer_explanation = CASE WHEN ? THEN ? ELSE answer_explanation END,
            chapter = ?,
            source_label = ?,
            sort_order = CASE WHEN ? = 0 THEN sort_order ELSE ? END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        updates,
    )
    conn.commit()

    return {
        "groups": labeled_groups,
        "updated_cards": len(updates),
        "skipped_multi_tag_cards": skipped_multi_tag,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Label repeated figure captions by image order.")
    parser.add_argument("db", nargs="*", type=Path, default=[DEFAULT_DB_PATH])
    parser.add_argument("--document-id")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    for db_path in args.db:
        conn = connect(db_path)
        init_db(conn)
        try:
            result = apply_panel_labels(conn, document_id=args.document_id)
        finally:
            conn.close()
        print(f"{db_path}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
