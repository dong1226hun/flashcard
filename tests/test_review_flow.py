import json
from pathlib import Path
import shutil
import sqlite3
import unittest
import uuid

from flashcard_pipeline.db import init_db, table_columns
from flashcard_pipeline.review_server import (
    add_card_image,
    list_available_images,
    merge_cards,
    remove_card_image,
    split_card,
    update_card,
    upload_card_image,
)
from flashcard_pipeline.study import set_favorite, set_past_exam


ONE_PIXEL_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lw9JzgAAAABJRU5ErkJggg=="


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
            (index, index, f"data/media/pdf/doc1/page-1/image-{index}.png", f"imagehash-{index}"),
        )
        image_id = conn.execute(
            "SELECT id FROM extracted_images WHERE page_image_index = ?",
            (index,),
        ).fetchone()["id"]
        cursor = conn.execute(
            """
            INSERT INTO cards
                (
                    document_id, source_page, caption_text, card_type, prompt_text,
                    answer_text, chapter, source_label, sort_order, confidence, notes
                )
            VALUES ('doc1', 1, ?, 'image', ?, ?, '18', ?, ?, 1.0, '')
            """,
            (
                f"Figure 18-21. Caption {index}",
                f"Prompt {index}",
                f"Answer {index}",
                f"Fig. 18-21{chr(64 + index)}.",
                index,
            ),
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
    def test_init_db_adds_template_fields_to_existing_cards(self):
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
            CREATE TABLE cards (
                id INTEGER PRIMARY KEY,
                document_id TEXT NOT NULL,
                source_page INTEGER NOT NULL,
                caption_text TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO documents (id, source_path, filename, file_hash, file_size)
            VALUES ('doc1', 'book.pdf', 'book.pdf', 'hash1', 123);
            INSERT INTO cards (id, document_id, source_page, caption_text, confidence)
            VALUES (10, 'doc1', 1, 'Figure 18-21. Migrated answer', 1.0);
            """
        )

        init_db(conn)

        columns = table_columns(conn, "cards")
        self.assertIn("card_type", columns)
        self.assertIn("prompt_text", columns)
        self.assertIn("answer_text", columns)
        row = conn.execute(
            """
            SELECT card_type, prompt_text, answer_text, answer_explanation, chapter, source_label
            FROM cards
            WHERE id = 10
            """
        ).fetchone()
        self.assertEqual(row["card_type"], "image")
        self.assertEqual(row["prompt_text"], "")
        self.assertEqual(row["answer_text"], "Migrated answer")
        self.assertEqual(row["answer_explanation"], "")
        self.assertEqual(row["chapter"], "18")
        self.assertEqual(row["source_label"], "Fig. 18-21.")
        conn.close()

    def test_merge_and_split_preserve_flags_and_template_answers(self):
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
        self.assertEqual(
            [row["answer_text"] for row in conn.execute("SELECT answer_text FROM cards ORDER BY id")],
            ["Caption 1", "Caption 2"],
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_past_exams").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_favorites").fetchone()[0], 2)
        conn.close()

    def test_update_card_applies_template_fields(self):
        conn = make_current_conn()

        payload = update_card(
            conn,
            1,
            card_type="multiple_choice",
            prompt_text="Which finding is present?",
            answer_text="Corticated border",
            answer_explanation="The border is smooth and corticated.",
            choices=[{"id": "a", "text": "Ill-defined"}, {"id": "b", "text": "Corticated border"}],
            answer_choice_ids=["b"],
            source_label="Fig. 18-21A.",
            chapter="18",
            sort_order=18021001,
            notes="reviewed",
        )

        row = conn.execute(
            """
            SELECT
                card_type, prompt_text, answer_text, answer_explanation,
                choices_json, answer_choice_ids_json, source_label, chapter,
                sort_order, notes
            FROM cards
            WHERE id = 1
            """
        ).fetchone()
        self.assertEqual(row["card_type"], "multiple_choice")
        self.assertEqual(row["prompt_text"], "Which finding is present?")
        self.assertEqual(row["answer_text"], "Corticated border")
        self.assertEqual(json.loads(row["answer_choice_ids_json"]), ["b"])
        self.assertEqual(row["source_label"], "Fig. 18-21A.")
        self.assertEqual(row["sort_order"], 18021001)
        self.assertEqual(row["notes"], "reviewed")
        self.assertEqual(payload["type"], "multiple_choice")
        self.assertEqual(payload["answer"]["choiceIds"], ["b"])
        conn.close()

    def test_list_available_images_marks_attached_images(self):
        conn = make_current_conn()

        payload = list_available_images(conn, 1)

        attached_by_id = {item["image_id"]: item["is_attached"] for item in payload["items"]}
        self.assertTrue(attached_by_id[1])
        self.assertFalse(attached_by_id[2])
        conn.close()

    def test_add_card_image_links_existing_image_without_duplicates(self):
        conn = make_current_conn()

        payload = add_card_image(conn, 1, 2)
        add_card_image(conn, 1, 2)

        self.assertEqual(payload["image_count"], 2)
        self.assertEqual(len(payload["images"]), 2)
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM card_images WHERE card_id = 1 AND image_id = 2",
            ).fetchone()[0],
            1,
        )
        conn.close()

    def test_remove_card_image_only_removes_card_link(self):
        conn = make_current_conn()

        payload = remove_card_image(conn, 1, 1)

        self.assertEqual(payload["image_count"] or 0, 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM card_images WHERE card_id = 1").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM extracted_images WHERE id = 1").fetchone()[0], 1)
        conn.close()

    def test_upload_card_image_creates_image_record_and_link(self):
        conn = make_current_conn()
        upload_root = Path("data") / "media" / "generated" / "test-uploads" / f"review-flow-{uuid.uuid4().hex}"
        self.addCleanup(lambda: shutil.rmtree(upload_root.parent, ignore_errors=True))

        payload = upload_card_image(
            conn,
            1,
            {
                "filename": "pixel.png",
                "content_type": "image/png",
                "data_base64": ONE_PIXEL_PNG,
            },
            upload_root=upload_root,
        )

        uploaded = payload["uploaded_image"]
        image_id = uploaded["image_id"]
        row = conn.execute("SELECT * FROM extracted_images WHERE id = ?", (image_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["document_id"], "doc1")
        self.assertEqual(row["page_number"], 1)
        self.assertEqual(row["xref"], 0)
        self.assertEqual(row["width"], 1)
        self.assertEqual(row["height"], 1)
        self.assertTrue(Path(row["file_path"]).exists())
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM card_images WHERE card_id = 1 AND image_id = ?",
                (image_id,),
            ).fetchone()[0],
            1,
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()
