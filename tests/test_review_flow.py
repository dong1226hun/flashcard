import sqlite3
import unittest

from flashcard_pipeline.db import init_db, table_exists
from flashcard_pipeline.review_server import merge_cards, split_card, update_card
from flashcard_pipeline.study import set_favorite, set_past_exam


def make_current_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.execute(
        """
        INSERT INTO documents (id, source_path, filename, file_hash, file_size)
        VALUES ('doc1', 'book.pdf', 'book.pdf', 'hash1', 123)
        """
    )
    for index in [1, 2]:
        conn.execute(
            """
            INSERT INTO extracted_images
                (
                    document_id, page_number, page_image_index, xref, file_path,
                    file_hash, ext, width, height, bbox_json
                )
            VALUES ('doc1', 1, ?, ?, ?, ?, 'png', 200, 120, '{}')
            """,
            (index, index, f"assets/image-{index}.png", f"imagehash-{index}"),
        )
        image_id = conn.execute(
            "SELECT id FROM extracted_images WHERE page_image_index = ?",
            (index,),
        ).fetchone()["id"]
        cursor = conn.execute(
            """
            INSERT INTO cards (document_id, source_page, caption_text, confidence, notes)
            VALUES ('doc1', 1, ?, 1.0, '')
            """,
            (f"Figure 18-21. Caption {index}",),
        )
        card_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO card_images (card_id, image_id, sort_order, source_caption_text)
            VALUES (?, ?, 0, ?)
            """,
            (card_id, image_id, f"Figure 18-21. Caption {index}"),
        )
    conn.commit()
    return conn


class ReviewFlowTests(unittest.TestCase):
    def test_init_db_migrates_legacy_rows_and_skips_rejected_cards(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_hash TEXT NOT NULL UNIQUE,
                file_size INTEGER NOT NULL,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE extracted_images (
                id INTEGER PRIMARY KEY,
                document_id TEXT NOT NULL,
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
                duplicate_of INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE card_candidates (
                id INTEGER PRIMARY KEY,
                document_id TEXT NOT NULL,
                image_id INTEGER NOT NULL,
                caption_block_id INTEGER,
                source_page INTEGER NOT NULL,
                caption_text TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE flashcards (
                id INTEGER PRIMARY KEY,
                document_id TEXT NOT NULL,
                source_candidate_id INTEGER NOT NULL,
                front_image_id INTEGER NOT NULL,
                back_caption TEXT NOT NULL
            );
            CREATE TABLE study_sessions (
                id INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                card_count INTEGER NOT NULL,
                reviewed_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                source_filter TEXT NOT NULL DEFAULT 'all'
            );
            CREATE TABLE study_reviews (
                id INTEGER PRIMARY KEY,
                session_id INTEGER NOT NULL,
                candidate_id INTEGER NOT NULL,
                result TEXT NOT NULL,
                reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE study_favorites (
                candidate_id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE study_past_exams (
                candidate_id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO documents (id, source_path, filename, file_hash, file_size)
            VALUES ('doc1', 'book.pdf', 'book.pdf', 'hash1', 123);
            INSERT INTO extracted_images
                (id, document_id, page_number, page_image_index, xref, file_path, file_hash, ext, width, height, bbox_json)
            VALUES
                (10, 'doc1', 1, 1, 1, 'assets/10.png', 'hash10', 'png', 100, 100, '{}'),
                (11, 'doc1', 1, 2, 2, 'assets/11.png', 'hash11', 'png', 100, 100, '{}'),
                (12, 'doc1', 1, 3, 3, 'assets/12.png', 'hash12', 'png', 100, 100, '{}');
            INSERT INTO card_candidates
                (id, document_id, image_id, source_page, caption_text, confidence, status, notes)
            VALUES
                (10, 'doc1', 10, 1, 'Figure 18-21. Active', 1.0, 'pending', ''),
                (11, 'doc1', 11, 1, 'Figure 18-22. Active', 1.0, 'approved', ''),
                (12, 'doc1', 12, 1, 'Figure 18-21. Merged child', 1.0, 'rejected', 'merged_pdf_figure_into=10');
            INSERT INTO study_sessions (id, card_count) VALUES (1, 2);
            INSERT INTO study_reviews (id, session_id, candidate_id, result) VALUES (1, 1, 10, 'correct');
            INSERT INTO study_favorites (candidate_id) VALUES (12);
            INSERT INTO study_past_exams (candidate_id) VALUES (10);
            """
        )

        init_db(conn)

        self.assertFalse(table_exists(conn, "card_candidates"))
        self.assertFalse(table_exists(conn, "flashcards"))
        self.assertEqual(
            [row["id"] for row in conn.execute("SELECT id FROM cards ORDER BY id")],
            [10, 11],
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM card_images WHERE card_id = 10").fetchone()[0],
            2,
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_past_exams").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_favorites").fetchone()[0], 0)
        self.assertEqual(
            conn.execute("SELECT card_id FROM study_reviews").fetchone()["card_id"],
            10,
        )
        conn.close()

    def test_merge_and_split_preserve_flags_and_source_captions(self):
        conn = make_current_conn()
        set_past_exam(conn, card_id=1, past_exam=True)
        set_favorite(conn, card_id=2, favorite=True)

        merge_cards(conn, [1, 2], 1)
        conn.commit()

        self.assertEqual(conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM card_images WHERE card_id = 1").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_past_exams WHERE card_id = 1").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_favorites WHERE card_id = 1").fetchone()[0], 1)

        images = conn.execute(
            """
            SELECT ci.*, i.page_number
            FROM card_images ci
            JOIN extracted_images i ON i.id = ci.image_id
            WHERE ci.card_id = 1
            ORDER BY ci.sort_order
            """
        ).fetchall()
        new_ids = split_card(conn, 1, images)
        conn.commit()

        self.assertEqual(len(new_ids), 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 2)
        self.assertEqual(
            [row["caption_text"] for row in conn.execute("SELECT caption_text FROM cards ORDER BY id")],
            ["Figure 18-21. Caption 1", "Figure 18-21. Caption 2"],
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_past_exams").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_favorites").fetchone()[0], 2)
        conn.close()

    def test_update_card_applies_answer_fields_to_db_caption(self):
        conn = make_current_conn()

        payload = update_card(
            conn,
            1,
            answer_title="골경화증",
            answer_detail="비교적 경계가 명확한 방사선불투과성 부위로 관찰된다.",
            notes="reviewed",
        )

        row = conn.execute("SELECT caption_text, notes FROM cards WHERE id = 1").fetchone()
        self.assertEqual(
            row["caption_text"],
            "Figure 18-21. 골경화증. 비교적 경계가 명확한 방사선불투과성 부위로 관찰된다.",
        )
        self.assertEqual(row["notes"], "reviewed")
        self.assertEqual(payload["answer_title"], "골경화증")
        self.assertEqual(payload["answer_detail"], "비교적 경계가 명확한 방사선불투과성 부위로 관찰된다.")
        conn.close()


if __name__ == "__main__":
    unittest.main()
