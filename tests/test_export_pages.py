import unittest

from flashcard_pipeline.export_pages import convert_card_paths, referenced_asset_paths


class ExportPagesTests(unittest.TestCase):
    def test_export_media_uses_static_urls_without_internal_file_paths(self):
        card = {
            "id": "1",
            "media": [
                {
                    "kind": "image",
                    "src": "/media/pdf/doc1/page-1/image-1.png",
                    "file_path": "data/media/pdf/doc1/page-1/image-1.png",
                }
            ],
        }

        converted = convert_card_paths(card)

        self.assertEqual(converted["media"][0]["src"], "media/pdf/doc1/page-1/image-1.png")
        self.assertNotIn("file_path", converted["media"][0])
        self.assertEqual(referenced_asset_paths([card]), {"data/media/pdf/doc1/page-1/image-1.png"})


if __name__ == "__main__":
    unittest.main()
