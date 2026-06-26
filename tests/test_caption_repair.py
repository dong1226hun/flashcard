import sqlite3
import unittest

from flashcard_pipeline.caption_repair import apply_caption_repairs, propose_caption_repairs
from flashcard_pipeline.db import init_db


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
    return conn


def add_text_block(conn, block_number, text, bbox_json):
    cursor = conn.execute(
        """
        INSERT INTO extracted_text_blocks
            (document_id, page_number, block_number, text, bbox_json)
        VALUES ('doc1', 1, ?, ?, ?)
        """,
        (block_number, text, bbox_json),
    )
    return int(cursor.lastrowid)


def add_card(conn, image_index, caption, image_bbox, caption_block_id=None):
    cursor = conn.execute(
        """
        INSERT INTO extracted_images
            (
                document_id, page_number, page_image_index, xref, file_path,
                file_hash, ext, width, height, bbox_json
            )
        VALUES ('doc1', 1, ?, ?, ?, ?, 'png', 200, 120, ?)
        """,
        (
            image_index,
            image_index,
            f"data/media/pdf/doc1/page-1/image-{image_index}.png",
            f"imagehash-{image_index}",
            image_bbox,
        ),
    )
    image_id = int(cursor.lastrowid)
    cursor = conn.execute(
        """
        INSERT INTO cards
            (document_id, caption_block_id, source_page, caption_text, confidence)
        VALUES ('doc1', ?, 1, ?, 0.4)
        """,
        (caption_block_id, caption),
    )
    card_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO card_images (card_id, image_id, sort_order, source_caption_text)
        VALUES (?, ?, 0, ?)
        """,
        (card_id, image_id, caption),
    )
    return card_id


class CaptionRepairTests(unittest.TestCase):
    def test_repairs_missing_caption_and_relabels_panels(self):
        conn = make_conn()
        caption = "Figure 16-1. Shared caption. A, first panel. B, second panel."
        block_id = add_text_block(conn, 1, caption, '{"x0": 100, "y0": 250, "x1": 300, "y1": 265}')
        add_card(
            conn,
            1,
            "section heading",
            '{"x0": 100, "y0": 100, "x1": 300, "y1": 240}',
        )
        add_card(
            conn,
            2,
            caption,
            '{"x0": 320, "y0": 100, "x1": 520, "y1": 240}',
            block_id,
        )
        conn.commit()

        result = apply_caption_repairs(conn)

        self.assertEqual(result["repaired_cards"], 1)
        rows = conn.execute(
            """
            SELECT id, caption_text
            FROM cards
            ORDER BY id
            """
        ).fetchall()
        self.assertEqual(rows[0]["caption_text"], "Figure 16-1A. Shared caption. A, first panel.")
        self.assertEqual(rows[1]["caption_text"], "Figure 16-1B. Shared caption. B, second panel.")
        conn.close()

    def test_prefers_caption_inside_lower_part_of_image(self):
        conn = make_conn()
        add_text_block(conn, 1, "Figure 25-18. Earlier figure.", '{"x0": 180, "y0": 276, "x1": 440, "y1": 286}')
        add_text_block(conn, 2, "Figure 25-19. Correct figure.", '{"x0": 180, "y0": 514, "x1": 440, "y1": 524}')
        add_card(
            conn,
            1,
            "body text",
            '{"x0": 119, "y0": 286, "x1": 310, "y1": 548}',
        )
        conn.commit()

        repairs = propose_caption_repairs(conn)

        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0].new_caption, "Figure 25-19. Correct figure.")
        self.assertEqual(repairs[0].card_id, 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
