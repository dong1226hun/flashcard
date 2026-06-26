from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .answer_fields import answer_fields_from_caption, answer_is_caption_derived, strip_leading_figure_label


DEFAULT_DB_PATH = Path("data") / "flashcards.sqlite"

CARD_TYPES = {"image", "multiple_choice", "short_answer"}
LEGACY_DEFAULT_PROMPT = "Study the prompt and recall the answer."
DASHES = r"\-\u2010\u2011\u2012\u2013\u2014\u2015\uff0d"
FIGURE_TAG_RE = re.compile(
    rf"(?:\uadf8\ub9bc|Fig\.?|Figure)\s*"
    rf"(?P<chapter>\d+)\s*[{DASHES}]\s*(?P<figure>\d+)"
    rf"(?P<label>[A-Za-z])?",
    re.IGNORECASE,
)


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    file_size INTEGER NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pdf_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    width REAL NOT NULL,
    height REAL NOT NULL,
    UNIQUE(document_id, page_number)
);

CREATE TABLE IF NOT EXISTS extracted_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    page_image_index INTEGER NOT NULL,
    xref INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    ext TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    bbox_json TEXT NOT NULL,
    is_duplicate INTEGER NOT NULL DEFAULT 0,
    duplicate_of INTEGER REFERENCES extracted_images(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id, page_number, page_image_index)
);

CREATE INDEX IF NOT EXISTS idx_extracted_images_doc_page
ON extracted_images(document_id, page_number);

CREATE INDEX IF NOT EXISTS idx_extracted_images_hash
ON extracted_images(file_hash);

CREATE TABLE IF NOT EXISTS extracted_text_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    block_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    bbox_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id, page_number, block_number)
);

CREATE INDEX IF NOT EXISTS idx_extracted_text_blocks_doc_page
ON extracted_text_blocks(document_id, page_number);

CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    caption_block_id INTEGER REFERENCES extracted_text_blocks(id) ON DELETE SET NULL,
    source_page INTEGER NOT NULL,
    caption_text TEXT NOT NULL DEFAULT '',
    card_type TEXT NOT NULL DEFAULT 'image'
        CHECK(card_type IN ('image', 'multiple_choice', 'short_answer')),
    prompt_text TEXT NOT NULL DEFAULT '',
    answer_text TEXT NOT NULL DEFAULT '',
    answer_explanation TEXT NOT NULL DEFAULT '',
    choices_json TEXT NOT NULL DEFAULT '[]',
    answer_choice_ids_json TEXT NOT NULL DEFAULT '[]',
    chapter TEXT NOT NULL DEFAULT 'Unknown',
    source_label TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cards_doc_page
ON cards(document_id, source_page);

CREATE TABLE IF NOT EXISTS card_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    image_id INTEGER NOT NULL REFERENCES extracted_images(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    source_caption_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(card_id, image_id),
    UNIQUE(card_id, sort_order)
);

CREATE INDEX IF NOT EXISTS idx_card_images_card
ON card_images(card_id, sort_order);

CREATE TABLE IF NOT EXISTS study_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    card_count INTEGER NOT NULL,
    reviewed_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'completed')),
    source_filter TEXT NOT NULL DEFAULT 'all'
);

CREATE TABLE IF NOT EXISTS study_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    result TEXT NOT NULL CHECK(result IN ('correct', 'wrong')),
    reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_study_reviews_session
ON study_reviews(session_id);

CREATE INDEX IF NOT EXISTS idx_study_reviews_card
ON study_reviews(card_id);

CREATE TABLE IF NOT EXISTS study_favorites (
    card_id INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS study_past_exams (
    card_id INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


CARD_COLUMN_ALTERS = {
    "card_type": "ALTER TABLE cards ADD COLUMN card_type TEXT NOT NULL DEFAULT 'image'",
    "prompt_text": "ALTER TABLE cards ADD COLUMN prompt_text TEXT NOT NULL DEFAULT ''",
    "answer_text": "ALTER TABLE cards ADD COLUMN answer_text TEXT NOT NULL DEFAULT ''",
    "answer_explanation": "ALTER TABLE cards ADD COLUMN answer_explanation TEXT NOT NULL DEFAULT ''",
    "choices_json": "ALTER TABLE cards ADD COLUMN choices_json TEXT NOT NULL DEFAULT '[]'",
    "answer_choice_ids_json": "ALTER TABLE cards ADD COLUMN answer_choice_ids_json TEXT NOT NULL DEFAULT '[]'",
    "chapter": "ALTER TABLE cards ADD COLUMN chapter TEXT NOT NULL DEFAULT 'Unknown'",
    "source_label": "ALTER TABLE cards ADD COLUMN source_label TEXT NOT NULL DEFAULT ''",
    "sort_order": "ALTER TABLE cards ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0",
}


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        is not None
    )


def table_columns(conn: sqlite3.Connection, name: str) -> set[str]:
    if not table_exists(conn, name):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({name})")}


def row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def append_note(current_notes: str, addition: str) -> str:
    current_notes = (current_notes or "").strip()
    return f"{current_notes}; {addition}" if current_notes else addition


def create_core_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def normalize_json_array(value: object) -> str:
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = []
    elif isinstance(value, list):
        parsed = value
    else:
        parsed = []
    return json.dumps(parsed if isinstance(parsed, list) else [], ensure_ascii=False)


def figure_metadata(caption: str) -> tuple[str, str, int]:
    match = FIGURE_TAG_RE.search(caption or "")
    if not match:
        return "Unknown", "", 0
    chapter = match.group("chapter")
    figure = match.group("figure")
    label = (match.group("label") or "").upper()
    panel_order = ord(label) - ord("A") + 1 if label else 0
    source_label = f"Fig. {chapter}-{figure}{label}."
    sort_order = int(chapter) * 1_000_000 + int(figure) * 1_000 + panel_order
    return chapter, source_label, sort_order


def fallback_sort_order(source_page: object, card_id: object) -> int:
    try:
        page = int(source_page or 0)
    except (TypeError, ValueError):
        page = 0
    try:
        ident = int(card_id or 0)
    except (TypeError, ValueError):
        ident = 0
    return page * 10_000 + ident


def migrate_card_template_fields(conn: sqlite3.Connection) -> None:
    if not table_exists(conn, "cards"):
        return

    columns = table_columns(conn, "cards")
    for name, statement in CARD_COLUMN_ALTERS.items():
        if name not in columns:
            conn.execute(statement)

    rows = conn.execute(
        """
        SELECT
            id,
            source_page,
            caption_text,
            card_type,
            prompt_text,
            answer_text,
            answer_explanation,
            choices_json,
            answer_choice_ids_json,
            chapter,
            source_label,
            sort_order
        FROM cards
        ORDER BY source_page, id
        """
    ).fetchall()
    for row in rows:
        caption = str(row["caption_text"] or "")
        chapter, source_label, sort_order = figure_metadata(caption)
        if sort_order == 0:
            sort_order = fallback_sort_order(row["source_page"], row["id"])

        card_type = str(row["card_type"] or "image")
        if card_type not in CARD_TYPES:
            card_type = "image"

        prompt_text = str(row["prompt_text"] or "")
        if prompt_text == LEGACY_DEFAULT_PROMPT:
            prompt_text = ""

        answer_text = str(row["answer_text"] or "")
        answer_explanation = str(row["answer_explanation"] or "")
        should_rebuild_answer = (
            card_type == "image"
            and (
                not answer_text
                or strip_leading_figure_label(answer_text) != answer_text
                or (answer_is_caption_derived(answer_text, caption) and not answer_explanation)
            )
        )
        if should_rebuild_answer:
            fields = answer_fields_from_caption(caption)
            answer_text = fields.answer_text
            answer_explanation = fields.answer_explanation
        else:
            answer_text = strip_leading_figure_label(answer_text)

        updates = {
            "card_type": card_type,
            "prompt_text": prompt_text,
            "answer_text": answer_text or answer_fields_from_caption(caption).answer_text,
            "answer_explanation": answer_explanation,
            "choices_json": normalize_json_array(row["choices_json"]),
            "answer_choice_ids_json": normalize_json_array(row["answer_choice_ids_json"]),
            "chapter": row["chapter"] if row["chapter"] and row["chapter"] != "Unknown" else chapter,
            "source_label": row["source_label"] or source_label,
            "sort_order": row["sort_order"] or sort_order,
        }
        conn.execute(
            """
            UPDATE cards
            SET
                card_type = ?,
                prompt_text = ?,
                answer_text = ?,
                answer_explanation = ?,
                choices_json = ?,
                answer_choice_ids_json = ?,
                chapter = ?,
                source_label = ?,
                sort_order = ?,
                updated_at = updated_at
            WHERE id = ?
            """,
            (
                updates["card_type"],
                updates["prompt_text"],
                updates["answer_text"],
                updates["answer_explanation"],
                updates["choices_json"],
                updates["answer_choice_ids_json"],
                updates["chapter"],
                updates["source_label"],
                updates["sort_order"],
                row["id"],
            ),
        )


def init_db(conn: sqlite3.Connection) -> None:
    create_core_schema(conn)
    migrate_card_template_fields(conn)
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_cards_template_fields
        ON cards(card_type, chapter, sort_order)
        """
    )
    conn.commit()
