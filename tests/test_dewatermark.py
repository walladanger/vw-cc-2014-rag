import unittest

from dewatermark_pdf import _FORM_SIGNATURE
from rebuild_clean_manuals import semantic_text


class DewatermarkTests(unittest.TestCase):
    def test_vag_full_form_signature(self):
        stream = (
            b"1 0 0 1 -37.3834 140.6457 cm\r"
            b"0.906 g\r1 i\r/RelativeColorimetric ri"
        )
        self.assertIsNotNone(_FORM_SIGNATURE.search(stream))

    def test_semantic_validation_ignores_spacing_only(self):
        self.assertEqual(
            semantic_text("start the Diagnosis . -- T23/12"),
            semantic_text("start the Diagnosis. - T23/12"),
        )
        self.assertNotEqual(semantic_text("25 Nm"), semantic_text("30 Nm"))


if __name__ == "__main__":
    unittest.main()
