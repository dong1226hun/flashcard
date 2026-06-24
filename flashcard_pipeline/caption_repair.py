from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .caption_labels import FIGURE_TAG_RE, apply_panel_labels
from .db import DEFAULT_DB_PATH, connect, init_db


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0


@dataclass(frozen=True)
class CaptionBlock:
    db_id: int
    text: str
    rect: Rect


@dataclass(frozen=True)
class CaptionRepair:
    card_id: int
    source_page: int
    old_caption: str
    new_caption: str
    caption_block_id: int
    score: float
    reason: str


def rect_from_json(value: str) -> Rect:
    raw = json.loads(value or "{}")
    return Rect(
        float(raw.get("x0", 0.0)),
        float(raw.get("y0", 0.0)),
        float(raw.get("x1", 0.0)),
        float(raw.get("y1", 0.0)),
    )


def horizontal_overlap_ratio(a: Rect, b: Rect) -> float:
    overlap = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    return overlap / max(1.0, min(a.width, b.width))


def is_strict_figure_caption(text: str) -> bool:
    return bool(FIGURE_TAG_RE.match((text or "").strip()))


def needs_caption_repair(caption: str) -> bool:
    return not FIGURE_TAG_RE.search(caption or "")


def score_figure_caption(image_rect: Rect, caption_rect: Rect) -> tuple[float, str]:
    h_overlap = horizontal_overlap_ratio(image_rect, caption_rect)
    below_gap = caption_rect.y0 - image_rect.y1
    above_gap = image_rect.y0 - caption_rect.y1
    inside = (
        image_rect.y0 - 8 <= caption_rect.y0
        and caption_rect.y1 <= image_rect.y1 + 12
        and h_overlap >= 0.05
    )

    if inside:
        relative_y = (caption_rect.center_y - image_rect.y0) / max(1.0, image_rect.height)
        score = 900.0 + (relative_y * 220.0) + (h_overlap * 100.0)
        return score, "inside"

    if -12 <= below_gap <= 420 and h_overlap >= 0.05:
        score = 1000.0 - max(0.0, below_gap) + (h_overlap * 120.0)
        return score, "below"

    if -12 <= above_gap <= 160 and h_overlap >= 0.05:
        score = 650.0 - max(0.0, above_gap) + (h_overlap * 80.0)
        return score, "above"

    dx = abs(image_rect.center_x - caption_rect.center_x)
    dy = abs(image_rect.center_y - caption_rect.center_y)
    score = 220.0 - (dx * 0.35) - (dy * 0.15) + (h_overlap * 50.0)
    return score, "nearest"


def load_figure_caption_blocks(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    page_number: int,
) -> list[CaptionBlock]:
    rows = conn.execute(
        """
        SELECT id, text, bbox_json
        FROM extracted_text_blocks
        WHERE document_id = ? AND page_number = ?
        ORDER BY block_number
        """,
        (document_id, page_number),
    ).fetchall()
    return [
        CaptionBlock(int(row["id"]), row["text"], rect_from_json(row["bbox_json"]))
        for row in rows
        if is_strict_figure_caption(row["text"])
    ]


def best_caption_block(image_rect: Rect, blocks: Iterable[CaptionBlock]) -> tuple[CaptionBlock | None, float, str]:
    best_block: CaptionBlock | None = None
    best_score = float("-inf")
    best_reason = ""
    for block in blocks:
        score, reason = score_figure_caption(image_rect, block.rect)
        if score > best_score:
            best_block = block
            best_score = score
            best_reason = reason
    if best_block is None:
        return None, 0.0, "none"
    return best_block, round(best_score, 3), best_reason


def propose_caption_repairs(
    conn: sqlite3.Connection,
    *,
    document_id: str | None = None,
) -> list[CaptionRepair]:
    where = "WHERE 1 = 1"
    params: list[str] = []
    if document_id:
        where += " AND c.document_id = ?"
        params.append(document_id)

    rows = conn.execute(
        f"""
        SELECT
            c.id,
            c.document_id,
            c.source_page,
            c.caption_text,
            i.bbox_json
        FROM cards c
        JOIN card_images ci ON ci.card_id = c.id
        JOIN extracted_images i ON i.id = ci.image_id
        {where}
          AND ci.sort_order = (
              SELECT MIN(sort_order) FROM card_images WHERE card_id = c.id
          )
        ORDER BY c.document_id, c.source_page, i.page_image_index, c.id
        """,
        params,
    ).fetchall()

    block_cache: dict[tuple[str, int], list[CaptionBlock]] = {}
    repairs: list[CaptionRepair] = []
    for row in rows:
        if not needs_caption_repair(row["caption_text"]):
            continue
        cache_key = (row["document_id"], int(row["source_page"]))
        if cache_key not in block_cache:
            block_cache[cache_key] = load_figure_caption_blocks(
                conn,
                document_id=row["document_id"],
                page_number=int(row["source_page"]),
            )
        block, score, reason = best_caption_block(rect_from_json(row["bbox_json"]), block_cache[cache_key])
        if block is None:
            continue
        repairs.append(
            CaptionRepair(
                card_id=int(row["id"]),
                source_page=int(row["source_page"]),
                old_caption=row["caption_text"],
                new_caption=block.text,
                caption_block_id=block.db_id,
                score=score,
                reason=reason,
            )
        )
    return repairs


def append_repair_note(current_notes: str, repair: CaptionRepair) -> str:
    previous = " ".join((repair.old_caption or "").split())[:80]
    note = (
        f"caption_repair=strict_figure_caption;"
        f" score={repair.score:.3f}; reason={repair.reason}; previous_caption={previous}"
    )
    return f"{current_notes}; {note}" if current_notes else note


def apply_caption_repairs(
    conn: sqlite3.Connection,
    *,
    document_id: str | None = None,
    relabel_panels: bool = True,
) -> dict:
    repairs = propose_caption_repairs(conn, document_id=document_id)
    for repair in repairs:
        row = conn.execute(
            "SELECT notes FROM cards WHERE id = ?",
            (repair.card_id,),
        ).fetchone()
        notes = append_repair_note(row["notes"] if row else "", repair)
        conn.execute(
            """
            UPDATE cards
            SET
                caption_text = ?,
                caption_block_id = ?,
                confidence = MAX(confidence, 0.95),
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (repair.new_caption, repair.caption_block_id, notes, repair.card_id),
        )

    conn.commit()

    label_summary = {
        "groups": 0,
        "updated_cards": 0,
        "skipped_multi_tag_cards": 0,
    }
    if relabel_panels:
        label_summary = apply_panel_labels(conn, document_id=document_id)

    return {
        "repaired_cards": len(repairs),
        "caption_label_groups": label_summary["groups"],
        "caption_label_updates": label_summary["updated_cards"],
        "skipped_multi_tag_cards": label_summary["skipped_multi_tag_cards"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair cards whose captions missed the real figure caption.")
    parser.add_argument("db", nargs="*", type=Path, default=[DEFAULT_DB_PATH])
    parser.add_argument("--document-id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-relabel-panels", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    for db_path in args.db:
        conn = connect(db_path)
        init_db(conn)
        try:
            if args.dry_run:
                repairs = propose_caption_repairs(conn, document_id=args.document_id)
                result = {
                    "repaired_cards": len(repairs),
                    "repairs": [
                        {
                            "card_id": repair.card_id,
                            "source_page": repair.source_page,
                            "old_caption": repair.old_caption,
                            "new_caption": repair.new_caption,
                            "score": repair.score,
                            "reason": repair.reason,
                        }
                        for repair in repairs
                    ],
                }
            else:
                result = apply_caption_repairs(
                    conn,
                    document_id=args.document_id,
                    relabel_panels=not args.no_relabel_panels,
                )
        finally:
            conn.close()
        print(f"{db_path}: {json.dumps(result, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
