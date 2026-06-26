import unittest

from flashcard_pipeline.answer_fields import answer_fields_from_caption, answer_is_caption_derived


class AnswerFieldTests(unittest.TestCase):
    def test_strips_figure_label_and_splits_title_from_explanation(self):
        fields = answer_fields_from_caption("그림 16-4A. 인접면우식증. A, 제2대구치 원심면의 초기우식.")

        self.assertEqual(fields.answer_text, "인접면우식증")
        self.assertEqual(fields.answer_explanation, "A, 제2대구치 원심면의 초기우식.")

    def test_keeps_single_disease_name_without_explanation(self):
        fields = answer_fields_from_caption("그림 16-9. 방사선우식증.")

        self.assertEqual(fields.answer_text, "방사선우식증")
        self.assertEqual(fields.answer_explanation, "")

    def test_removes_panel_prefix_from_answer(self):
        fields = answer_fields_from_caption(
            "그림 20-5A. A~D, 골경화증. 비교적 경계가 명확한 방사선불투과성 부위로 관찰된다."
        )

        self.assertEqual(fields.answer_text, "골경화증")
        self.assertEqual(fields.answer_explanation, "비교적 경계가 명확한 방사선불투과성 부위로 관찰된다.")

    def test_extracts_disease_after_occurrence_context(self):
        fields = answer_fields_from_caption("그림 21-9. 상악에 발생한 치성각화낭. 둥근 형태를 보인다.")

        self.assertEqual(fields.answer_text, "치성각화낭")
        self.assertEqual(fields.answer_explanation, "둥근 형태를 보인다.")

    def test_splits_inline_panel_marker_after_disease_name(self):
        fields = answer_fields_from_caption("그림 23-12A. 법랑모세암종 A, 좌측 상악에서 병소가 관찰된다.")

        self.assertEqual(fields.answer_text, "법랑모세암종")
        self.assertEqual(fields.answer_explanation, "A, 좌측 상악에서 병소가 관찰된다.")

    def test_detects_existing_caption_derived_answer(self):
        self.assertTrue(answer_is_caption_derived("인접면우식증", "그림 16-4A. 인접면우식증. A, 설명."))
        self.assertFalse(answer_is_caption_derived("사용자 직접 입력", "그림 16-4A. 인접면우식증. A, 설명."))


if __name__ == "__main__":
    unittest.main()
