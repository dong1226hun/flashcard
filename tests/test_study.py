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
    split_answer_caption,
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
            (index, index, index, f"assets/image-{index}.png", f"imagehash-{index}"),
        )
        image_id = conn.execute(
            "SELECT id FROM extracted_images WHERE file_hash = ?",
            (f"imagehash-{index}",),
        ).fetchone()["id"]
        cursor = conn.execute(
            """
            INSERT INTO cards (document_id, source_page, caption_text, confidence)
            VALUES ('doc1', ?, ?, 1.0)
            """,
            (index, f"Figure {index}-1. Caption"),
        )
        card_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO card_images (card_id, image_id, sort_order, source_caption_text)
            VALUES (?, ?, 0, ?)
            """,
            (card_id, image_id, f"Figure {index}-1. Caption"),
        )
    conn.commit()
    return conn


class StudyTests(unittest.TestCase):
    def test_create_session_uses_all_cards(self):
        conn = make_conn()

        session = create_session(conn, requested_count=10)

        self.assertEqual(session["card_count"], 4)
        self.assertEqual([card["card_id"] for card in session["cards"]], [1, 2, 3, 4])
        conn.close()

    def test_create_session_can_filter_favorites(self):
        conn = make_conn()
        set_favorite(conn, card_id=2, favorite=True)

        session = create_session(conn, requested_count=10, source="favorites")

        self.assertEqual(session["card_count"], 1)
        self.assertEqual(session["cards"][0]["card_id"], 2)
        self.assertTrue(session["cards"][0]["is_favorite"])
        conn.close()

    def test_create_session_can_filter_past_exams(self):
        conn = make_conn()
        set_past_exam(conn, card_id=3, past_exam=True)

        session = create_session(conn, requested_count=10, source="past_exams")

        self.assertEqual(session["card_count"], 1)
        self.assertEqual(session["cards"][0]["card_id"], 3)
        self.assertTrue(session["cards"][0]["is_past_exam"])
        conn.close()

    def test_create_session_can_filter_latest_wrong_cards(self):
        conn = make_conn()
        first = create_session(conn, requested_count=2)
        wrong_card_id = first["cards"][0]["card_id"]
        corrected_card_id = first["cards"][1]["card_id"]
        record_review(
            conn,
            session_id=first["session_id"],
            card_id=wrong_card_id,
            result="wrong",
        )
        record_review(
            conn,
            session_id=first["session_id"],
            card_id=corrected_card_id,
            result="wrong",
        )
        second = create_session(conn, requested_count=1)
        record_review(
            conn,
            session_id=second["session_id"],
            card_id=corrected_card_id,
            result="correct",
        )

        session = create_session(conn, requested_count=10, source="wrong")

        self.assertEqual(session["card_count"], 1)
        self.assertEqual(session["cards"][0]["card_id"], wrong_card_id)
        self.assertEqual(session["cards"][0]["last_review_result"], "wrong")
        conn.close()

    def test_create_session_can_filter_chapter_with_all_cards(self):
        conn = make_conn()

        session = create_session(conn, requested_count="all", source="chapter", chapter="2")

        self.assertEqual(session["card_count"], 1)
        self.assertEqual(session["cards"][0]["chapter"], "2")
        conn.close()

    def test_session_limit_defaults_to_all_cards(self):
        self.assertIsNone(normalize_limit(None))
        self.assertIsNone(normalize_limit("not-a-number"))

    def test_split_answer_caption_uses_title_like_disease_name(self):
        result = split_answer_caption("그림 16-4A. 인접면우식증. A, 제2대구치 원심면의 초기우식.")

        self.assertEqual(result["answer_title"], "인접면우식증")
        self.assertEqual(result["answer_detail"], "A, 제2대구치 원심면의 초기우식.")

    def test_split_answer_caption_uses_first_caption_sentence_as_title(self):
        result = split_answer_caption(
            "그림 16-2A. 교익방사선영상. A, B는 같은 환자의 영상으로 B는 A를 부분 확대한 것이다. "
            "상악 제1대구치의 근심면과 하악 제1대구치 원심면에서 인접면우식이 관찰된다."
        )

        self.assertEqual(result["answer_title"], "교익방사선영상")
        self.assertEqual(
            result["answer_detail"],
            "A, B는 같은 환자의 영상으로 B는 A를 부분 확대한 것이다. "
            "상악 제1대구치의 근심면과 하악 제1대구치 원심면에서 인접면우식이 관찰된다.",
        )

    def test_split_answer_caption_cleans_panel_range_from_title(self):
        result = split_answer_caption(
            "그림 20-5A. A~D, 골경화증. 비교적 경계가 명확한 방사선불투과성 부위로 관찰된다."
        )

        self.assertEqual(result["answer_title"], "골경화증")
        self.assertEqual(result["answer_detail"], "비교적 경계가 명확한 방사선불투과성 부위로 관찰된다.")

    def test_split_answer_caption_does_not_promote_panel_sentence(self):
        result = split_answer_caption(
            "그림 16-13A. A의 제1유구치는 치수노출이 확실하다고 할 수 있으나 B의 제1유구치는 임상적인 확인이 필요하다."
        )

        self.assertEqual(result["answer_title"], "")
        self.assertEqual(
            result["answer_detail"],
            "A의 제1유구치는 치수노출이 확실하다고 할 수 있으나 B의 제1유구치는 임상적인 확인이 필요하다.",
        )

    def test_create_session_orders_by_figure_number_before_page_order(self):
        conn = make_conn()
        updates = [
            ("Figure 16-8A. Later figure.", 9, 1),
            ("Figure 16-7A. Earlier figure.", 9, 2),
            ("Figure 16-8B. Later figure panel B.", 8, 3),
            ("Figure 16-9. Latest figure.", 10, 4),
        ]
        for caption, source_page, card_id in updates:
            conn.execute(
                """
                UPDATE cards
                SET caption_text = ?, source_page = ?
                WHERE id = ?
                """,
                (caption, source_page, card_id),
            )
        conn.commit()

        session = create_session(conn, requested_count="all")

        self.assertEqual(
            [card["caption_text"] for card in session["cards"][:3]],
            [
                "Figure 16-7A. Earlier figure.",
                "Figure 16-8A. Later figure.",
                "Figure 16-8B. Later figure panel B.",
            ],
        )
        conn.close()

    def test_apply_panel_labels_uses_current_image_order(self):
        conn = make_conn()
        conn.execute(
            """
            UPDATE cards
            SET caption_text = 'Figure 16-1. Shared caption'
            WHERE source_page IN (1, 2)
            """
        )
        conn.commit()

        result = apply_panel_labels(conn)

        rows = conn.execute(
            """
            SELECT caption_text
            FROM cards
            WHERE source_page IN (1, 2)
            ORDER BY source_page, id
            """
        ).fetchall()
        self.assertEqual(result["updated_cards"], 2)
        self.assertEqual(rows[0]["caption_text"], "Figure 16-1A. Shared caption")
        self.assertEqual(rows[1]["caption_text"], "Figure 16-1B. Shared caption")
        conn.close()

    def test_apply_panel_labels_removes_direct_duplicate_panel_marker(self):
        conn = make_conn()
        conn.execute(
            """
            UPDATE cards
            SET caption_text = 'Figure 16-13. A, first panel. B, second panel.'
            WHERE source_page IN (1, 2)
            """
        )
        conn.commit()

        apply_panel_labels(conn)

        rows = conn.execute(
            """
            SELECT caption_text
            FROM cards
            WHERE source_page IN (1, 2)
            ORDER BY source_page, id
            """
        ).fetchall()
        self.assertEqual(rows[0]["caption_text"], "Figure 16-13A. first panel.")
        self.assertEqual(rows[1]["caption_text"], "Figure 16-13B. second panel.")
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

    def test_known_chapter_titles_match_textbook(self):
        self.assertEqual(chapter_title("16"), "치아우식증의 영상진단")
        self.assertEqual(chapter_title("28"), "구강악안면부 외상의 진단")

    def test_record_review_creates_review_row(self):
        conn = make_conn()
        session = create_session(conn, requested_count=1)
        card_id = session["cards"][0]["card_id"]

        result = record_review(
            conn,
            session_id=session["session_id"],
            card_id=card_id,
            result="correct",
        )

        self.assertTrue(result["completed"])
        self.assertEqual(result["reviewed_count"], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_reviews").fetchone()[0], 1)
        conn.close()

    def test_study_summary_counts_results(self):
        conn = make_conn()
        session = create_session(conn, requested_count=2)
        set_past_exam(conn, card_id=session["cards"][0]["card_id"], past_exam=True)
        record_review(
            conn,
            session_id=session["session_id"],
            card_id=session["cards"][0]["card_id"],
            result="correct",
        )
        record_review(
            conn,
            session_id=session["session_id"],
            card_id=session["cards"][1]["card_id"],
            result="wrong",
        )

        summary = study_summary(conn)

        self.assertEqual(summary["available_cards"], 4)
        self.assertEqual(summary["past_exam_cards"], 1)
        self.assertEqual(summary["total_reviews"], 2)
        self.assertEqual(summary["reviewed_cards"], 2)
        self.assertEqual(summary["correct"], 1)
        self.assertEqual(summary["wrong"], 1)
        self.assertEqual(summary["unsure"], 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()
