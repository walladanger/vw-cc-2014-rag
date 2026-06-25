import tempfile
import unittest
from pathlib import Path

import fitz

from manual_review import infer_page_offset, visible_page_text


class ManualReviewTests(unittest.TestCase):
    def test_visible_text_ignores_rotated_watermark(self):
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Service procedure text")
        page.insert_text((100, 200), "Protected by copyright", rotate=90)
        text = visible_page_text(page)
        document.close()
        self.assertIn("Service procedure text", text)
        self.assertNotIn("Protected by copyright", text)

    def test_page_offset_matches_trimmed_front_matter(self):
        original = fitz.open()
        for value in ("Cover", "Legal", "Procedure A", "Procedure B"):
            page = original.new_page()
            page.insert_text((72, 72), value)
        processed = fitz.open()
        for value in ("Procedure A", "Procedure B"):
            page = processed.new_page()
            page.insert_text((72, 72), value)
        self.assertEqual(infer_page_offset(original, processed), 2)
        original.close()
        processed.close()


if __name__ == "__main__":
    unittest.main()
