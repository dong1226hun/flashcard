import json
import sqlite3
import unittest

from flashcard_pipeline.caption_labels import apply_panel_labels
from flashcard_pipeline.db import init_db
from flashcard_pipeline.study import (
    chapter_title,
    create_session,
    normalize_limit,
    record_review,
    set_favorite,
    set_past_exam,
    study_sections,
    study_summary,
)


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.execute(
        """
        INSERT INTO documents (id, source_path, filename, file_hash, file_size)
        VALUES ('doc1', 'book.pdf', 'book.pdf', 'hash1', 123)
        """
    )
    for index in range(1, 5):
        conn.execute(
            """
            INSERT INTO extracted_images
                (
                    document_id, page_number, page_image_index, xref, file_path,
                    file_hash, ext, width, height, bbox_json
                )
            VALUES ('doc1', ?, ?, ?, ?, ?, 'png', 200, 120, '{}')
            """,
            (index, index, index, f"data/media/pdf/doc1/page-{index}/image-{index}.png", f"imagehash-{index}"),
        )
        image_id = conn.execute(
            "SELECT id FROM extracted_images WHERE file_hash = ?",
            (f"imagehash-{index}",),
        ).fetchone()["id"]
        cursor = conn.execute(
            """
            INSERT INTO cards
                (
                    document_id, source_page, caption_text, card_type, prompt_text,
                    answer_text, answer_explanation, chapter, source_label,
                    sort_order, confidence
                )
            VALUES ('doc1', ?, ?, 'image', ?, ?, ?, ?, ?, ?, 1.0)
            """,
            (
                index,
                f"Figure {index}-1. Source caption {index}",
                f"Prompt {index}",
                f"Answer {index}",
                f"Explanation {index}",
                str(index),
                f"Fig. {index}-1.",
                index,
            ),
        )
        card_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO card_images (card_id, image_id, sort_order, source_caption_text)
            VALUES (?, ?, 0, ?)
            """,
            (card_id, image_id, f"Figure {index}-1. Source caption {index}"),
        )
    conn.commit()
    return conn


class StudyTests(unittest.TestCase):
    def test_create_session_uses_all_cards_with_template_schema(self):
        conn = make_conn()

        session = create_session(conn, requested_count=10)

        self.assertEqual(session["card_count"], 4)
        self.assertEqual([card["card_id"] for card in session["cards"]], [1, 2, 3, 4])
        first = session["cards"][0]
        self.assertEqual(first["type"], "image")
        self.assertEqual(first["prompt"], {"text": "Prompt 1"})
        self.assertEqual(first["answer"]["text"], "Answer 1")
        self.assertEqual(first["answer"]["explanation"], "Explanation 1")
        self.assertEqual(first["meta"]["chapter"], "1")
        self.assertEqual(first["media"][0]["src"], "/media/pdf/doc1/page-1/image-1.png")
        self.assertNotIn("file_path", first["media"][0])
        conn.close()

    def test_create_session_supports_non_image_card_types(self):
        conn = make_conn()
        conn.execute(
            """
            INSERT INTO cards
                (
                    document_id, source_page, caption_text, card_type, prompt_text,
                    answer_text, choices_json, answer_choice_ids_json, chapter,
                    source_label, sort_order, confidence
                )
            VALUES ('doc1', 10, '', 'multiple_choice', ?, ?, ?, ?, 'quiz', 'Quiz 1', 10, 1.0)
            """,
            (
                "Pick the correct option.",
                "Option B",
                json.dumps([{"id": "a", "text": "Option A"}, {"id": "b", "text": "Option B"}]),
                json.dumps(["b"]),
            ),
        )
        conn.execute(
            """
            INSERT INTO cards
                (
                    document_id, source_page, caption_text, card_type, prompt_text,
                    answer_text, chapter, source_label, sort_order, confidence
                )
            VALUES ('doc1', 11, '', 'short_answer', 'Define the term.', 'Definition', 'quiz', 'Quiz 2', 11, 1.0)
            """
        )
        conn.commit()

        session = create_session(conn, requested_count="all", source="chapter", chapter="quiz")

        self.assertEqual([card["type"] for card in session["cards"]], ["multiple_choice", "short_answer"])
        self.assertEqual(session["cards"][0]["choices"][1]["id"], "b")
        self.assertEqual(session["cards"][0]["answer"]["choiceIds"], ["b"])
        self.assertEqual(session["cards"][1]["media"], [])
        conn.close()

    def test_create_session_can_filter_favorites(self):
        conn = make_conn()
        set_favorite(conn, card_id=2, favorite=True)

        session = create_session(conn, requested_count=10, source="favorites")

        self.assertEqual(session["card_count"], 1)
        self.assertEqual(session["cards"][0]["card_id"], 2)
        self.assertTrue(session["cards"][0]["review"]["favorite"])
        conn.close()

    def test_create_session_can_filter_past_exams(self):
        conn = make_conn()
        set_past_exam(conn, card_id=3, past_exam=True)

        session = create_session(conn, requested_count=10, source="past_exams")

        self.assertEqual(session["card_count"], 1)
        self.assertEqual(session["cards"][0]["card_id"], 3)
        self.assertTrue(session["cards"][0]["review"]["pastExam"])
        conn.close()

    def test_create_session_can_filter_latest_wrong_cards(self):
        conn = make_conn()
        first = create_session(conn, requested_count=2)
        wrong_card_id = first["cards"][0]["card_id"]
        corrected_card_id = first["cards"][1]["card_id"]
        record_review(conn, session_id=first["session_id"], card_id=wrong_card_id, result="wrong")
        record_review(conn, session_id=first["session_id"], card_id=corrected_card_id, result="wrong")
        second = create_session(conn, requested_count=1)
        record_review(conn, session_id=second["session_id"], card_id=corrected_card_id, result="correct")

        session = create_session(conn, requested_count=10, source="wrong")

        self.assertEqual(session["card_count"], 1)
        self.assertEqual(session["cards"][0]["card_id"], wrong_card_id)
        self.assertEqual(session["cards"][0]["review"]["lastResult"], "wrong")
        conn.close()

    def test_create_session_can_filter_chapter_with_all_cards(self):
        conn = make_conn()

        session = create_session(conn, requested_count="all", source="chapter", chapter="2")

        self.assertEqual(session["card_count"], 1)
        self.assertEqual(session["cards"][0]["meta"]["chapter"], "2")
        conn.close()

    def test_create_session_can_combine_frontend_filters(self):
        conn = make_conn()
        conn.execute(
            """
            UPDATE cards
            SET card_type = 'multiple_choice', prompt_text = 'Find the target lesion'
            WHERE id = 3
            """
        )
        conn.commit()

        session = create_session(
            conn,
            requested_count="all",
            chapter="3",
            card_type="multiple_choice",
            q="target",
        )

        self.assertEqual(session["card_count"], 1)
        self.assertEqual(session["cards"][0]["card_id"], 3)
        self.assertEqual(session["cards"][0]["type"], "multiple_choice")
        conn.close()

    def test_session_limit_defaults_to_all_cards(self):
        self.assertIsNone(normalize_limit(None))
        self.assertIsNone(normalize_limit("not-a-number"))

    def test_create_session_orders_by_explicit_sort_order(self):
        conn = make_conn()
        updates = [(30, 1), (10, 2), (20, 3), (40, 4)]
        for sort_order, card_id in updates:
            conn.execute("UPDATE cards SET sort_order = ? WHERE id = ?", (sort_order, card_id))
        conn.commit()

        session = create_session(conn, requested_count="all")

        self.assertEqual([card["card_id"] for card in session["cards"]], [2, 3, 1, 4])
        conn.close()

    def test_apply_panel_labels_updates_caption_and_template_answer_when_unedited(self):
        conn = make_conn()
        conn.execute(
            """
            UPDATE cards
            SET
                caption_text = 'Figure 16-1. Shared caption',
                answer_text = 'Figure 16-1. Shared caption'
            WHERE source_page IN (1, 2)
            """
        )
        conn.commit()

        result = apply_panel_labels(conn)

        rows = conn.execute(
            """
            SELECT caption_text, answer_text, answer_explanation, source_label
            FROM cards
            WHERE source_page IN (1, 2)
            ORDER BY source_page, id
            """
        ).fetchall()
        self.assertEqual(result["updated_cards"], 2)
        self.assertEqual(rows[0]["caption_text"], "Figure 16-1A. Shared caption")
        self.assertEqual(rows[0]["answer_text"], "Shared caption")
        self.assertEqual(rows[0]["answer_explanation"], "")
        self.assertEqual(rows[0]["source_label"], "Fig. 16-1A.")
        self.assertEqual(rows[1]["caption_text"], "Figure 16-1B. Shared caption")
        conn.close()

    def test_known_chapter_title_has_template_default(self):
        self.assertEqual(chapter_title("16"), "단원 16")
        self.assertEqual(chapter_title("Unknown"), "")

    def test_record_review_creates_review_row(self):
        conn = make_conn()
        session = create_session(conn, requested_count=1)
        card_id = session["cards"][0]["card_id"]

        result = record_review(conn, session_id=session["session_id"], card_id=card_id, result="correct")

        self.assertTrue(result["completed"])
        self.assertEqual(result["reviewed_count"], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_reviews").fetchone()[0], 1)
        conn.close()

    def test_study_sections_counts_all_favorites_past_exams_and_chapters(self):
        conn = make_conn()
        set_favorite(conn, card_id=1, favorite=True)
        set_past_exam(conn, card_id=2, past_exam=True)

        sections = study_sections(conn)

        self.assertEqual(sections["all"], 4)
        self.assertEqual(sections["favorites"], 1)
        self.assertEqual(sections["past_exams"], 1)
        self.assertEqual(sections["wrong"], 0)
        self.assertEqual(
            {item["chapter"]: item["count"] for item in sections["chapters"]},
            {"1": 1, "2": 1, "3": 1, "4": 1},
        )
        conn.close()

    def test_study_summary_counts_results(self):
        conn = make_conn()
        session = create_session(conn, requested_count=2)
        set_past_exam(conn, card_id=session["cards"][0]["card_id"], past_exam=True)
        record_review(conn, session_id=session["session_id"], card_id=session["cards"][0]["card_id"], result="correct")
        record_review(conn, session_id=session["session_id"], card_id=session["cards"][1]["card_id"], result="wrong")

        summary = study_summary(conn)

        self.assertEqual(summary["available_cards"], 4)
        self.assertEqual(summary["past_exam_cards"], 1)
        self.assertEqual(summary["total_reviews"], 2)
        self.assertEqual(summary["reviewed_cards"], 2)
        self.assertEqual(summary["correct"], 1)
        self.assertEqual(summary["wrong"], 1)
        self.assertNotIn("unsure", summary)
        conn.close()


if __name__ == "__main__":
    unittest.main()
