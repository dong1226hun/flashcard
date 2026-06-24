import unittest

from flashcard_pipeline.extract_pdf import Rect, TextBlock, match_caption, score_caption


class CaptionMatchingTests(unittest.TestCase):
    def test_prefers_caption_below_image(self):
        image = Rect(100, 100, 300, 240)
        caption = TextBlock(1, 1, 1, "그림 1. 파노라마 영상 예시", Rect(105, 248, 295, 272))
        far_text = TextBlock(2, 1, 2, "본문 설명입니다", Rect(400, 100, 520, 160))

        match = match_caption(image, [far_text, caption])

        self.assertEqual(match.block, caption)
        self.assertGreaterEqual(match.confidence, 0.7)

    def test_penalizes_far_text(self):
        image = Rect(100, 100, 300, 240)
        far_text = TextBlock(1, 1, 1, "그림 2. 멀리 있는 텍스트", Rect(100, 600, 300, 630))

        score, _ = score_caption(image, far_text)

        self.assertLess(score, 0.3)

    def test_single_panel_label_is_not_treated_as_caption(self):
        image = Rect(100, 100, 300, 240)
        label = TextBlock(1, 1, 1, "A", Rect(120, 246, 132, 258))

        score, _ = score_caption(image, label)

        self.assertLessEqual(score, 0.1)


if __name__ == "__main__":
    unittest.main()
