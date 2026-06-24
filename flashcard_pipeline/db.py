from __future__ import annotations

import re
import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("data") / "flashcards.sqlite"


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
    result TEXT NOT NULL CHECK(result IN ('correct', 'wrong', 'unsure')),
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


def legacy_merge_target(notes: str) -> int | None:
    match = re.search(r"merged_pdf_figure_into=(\d+)", notes or "")
    return int(match.group(1)) if match else None


def create_core_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def rename_legacy_study_tables(conn: sqlite3.Connection) -> dict[str, str]:
    renamed: dict[str, str] = {}
    for table in ("study_favorites", "study_past_exams", "study_reviews"):
        if "candidate_id" not in table_columns(conn, table):
            continue
        legacy_name = f"{table}_legacy"
        conn.execute(f"DROP TABLE IF EXISTS {legacy_name}")
        conn.execute(f"ALTER TABLE {table} RENAME TO {legacy_name}")
        renamed[table] = legacy_name
    return renamed


def copy_legacy_study_tables(conn: sqlite3.Connection, legacy_tables: dict[str, str]) -> None:
    favorites = legacy_tables.get("study_favorites")
    if favorites and table_exists(conn, favorites):
        conn.execute(
            f"""
            INSERT OR IGNORE INTO study_favorites (card_id, created_at)
            SELECT candidate_id, created_at
            FROM {favorites}
            WHERE candidate_id IN (SELECT id FROM cards)
            """
        )
        conn.execute(f"DROP TABLE {favorites}")

    past_exams = legacy_tables.get("study_past_exams")
    if past_exams and table_exists(conn, past_exams):
        conn.execute(
            f"""
            INSERT OR IGNORE INTO study_past_exams (card_id, created_at)
            SELECT candidate_id, created_at
            FROM {past_exams}
            WHERE candidate_id IN (SELECT id FROM cards)
            """
        )
        conn.execute(f"DROP TABLE {past_exams}")

    reviews = legacy_tables.get("study_reviews")
    if reviews and table_exists(conn, reviews):
        conn.execute(
            f"""
            INSERT INTO study_reviews (id, session_id, card_id, result, reviewed_at)
            SELECT id, session_id, candidate_id, result, reviewed_at
            FROM {reviews}
            WHERE candidate_id IN (SELECT id FROM cards)
            """
        )
        conn.execute(f"DROP TABLE {reviews}")


def migrate_legacy_schema(conn: sqlite3.Connection) -> None:
    if not table_exists(conn, "card_candidates") or table_exists(conn, "cards"):
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    legacy_study_tables = rename_legacy_study_tables(conn)
    create_core_schema(conn)

    active_rows = conn.execute(
        """
        SELECT *
        FROM card_candidates
        WHERE status != 'rejected'
        ORDER BY id
        """
    ).fetchall()

    for row in active_rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO cards
                (id, document_id, caption_block_id, source_page, caption_text,
                 confidence, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["document_id"],
                row["caption_block_id"],
                row["source_page"],
                row["caption_text"],
                row["confidence"],
                row["notes"],
                row["created_at"],
                row["updated_at"],
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO card_images
                (card_id, image_id, sort_order, source_caption_text)
            VALUES (?, ?, 0, ?)
            """,
            (row["id"], row["image_id"], row["caption_text"]),
        )

    merged_rows = conn.execute(
        """
        SELECT id, image_id, caption_text, notes
        FROM card_candidates
        WHERE status = 'rejected'
          AND notes LIKE '%merged_pdf_figure_into=%'
        ORDER BY id
        """
    ).fetchall()
    next_order: dict[int, int] = {
        int(row["card_id"]): int(row["next_sort"])
        for row in conn.execute(
            """
            SELECT card_id, COALESCE(MAX(sort_order), -1) + 1 AS next_sort
            FROM card_images
            GROUP BY card_id
            """
        )
    }
    for row in merged_rows:
        target_id = legacy_merge_target(row["notes"])
        if target_id is None or not conn.execute("SELECT 1 FROM cards WHERE id = ?", (target_id,)).fetchone():
            continue
        sort_order = next_order.get(target_id, 0)
        next_order[target_id] = sort_order + 1
        conn.execute(
            """
            INSERT OR IGNORE INTO card_images
                (card_id, image_id, sort_order, source_caption_text)
            VALUES (?, ?, ?, ?)
            """,
            (target_id, row["image_id"], sort_order, row["caption_text"]),
        )

    copy_legacy_study_tables(conn, legacy_study_tables)
    conn.executescript(
        """
        DROP TABLE IF EXISTS flashcards;
        DROP TABLE IF EXISTS card_candidates;
        DROP INDEX IF EXISTS idx_card_candidates_status;
        """
    )
    conn.execute("PRAGMA foreign_keys = ON")


def migrate_study_tables(conn: sqlite3.Connection) -> None:
    if "candidate_id" in table_columns(conn, "study_favorites"):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS study_favorites_new (
                card_id INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO study_favorites_new (card_id, created_at)
            SELECT candidate_id, created_at
            FROM study_favorites
            WHERE candidate_id IN (SELECT id FROM cards)
            """
        )
        conn.execute("DROP TABLE study_favorites")
        conn.execute("ALTER TABLE study_favorites_new RENAME TO study_favorites")

    if "candidate_id" in table_columns(conn, "study_past_exams"):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS study_past_exams_new (
                card_id INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO study_past_exams_new (card_id, created_at)
            SELECT candidate_id, created_at
            FROM study_past_exams
            WHERE candidate_id IN (SELECT id FROM cards)
            """
        )
        conn.execute("DROP TABLE study_past_exams")
        conn.execute("ALTER TABLE study_past_exams_new RENAME TO study_past_exams")

    if "candidate_id" in table_columns(conn, "study_reviews"):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS study_reviews_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                result TEXT NOT NULL CHECK(result IN ('correct', 'wrong', 'unsure')),
                reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO study_reviews_new (id, session_id, card_id, result, reviewed_at)
            SELECT id, session_id, candidate_id, result, reviewed_at
            FROM study_reviews
            WHERE candidate_id IN (SELECT id FROM cards)
            """
        )
        conn.execute("DROP TABLE study_reviews")
        conn.execute("ALTER TABLE study_reviews_new RENAME TO study_reviews")


def init_db(conn: sqlite3.Connection) -> None:
    migrate_legacy_schema(conn)
    migrate_study_tables(conn)
    create_core_schema(conn)
    conn.commit()
