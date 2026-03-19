from django.test import SimpleTestCase

from .utils import normalize_ordered_list_numbering


class NormalizeOrderedListNumberingTests(SimpleTestCase):
    def test_normalizes_repeated_markers_with_nested_bullets(self):
        text = "\n".join(
            [
                "### How Car Engines Work",
                "",
                "1. **Intake Stroke**:",
                "   - The engine draws in air and fuel.",
                "",
                "1. **Compression Stroke**:",
                "   - The piston compresses the mixture.",
                "",
                "1. **Power Stroke**:",
                "   - The spark plug ignites the mixture.",
            ]
        )

        self.assertEqual(
            normalize_ordered_list_numbering(text),
            "\n".join(
                [
                    "### How Car Engines Work",
                    "",
                    "1. **Intake Stroke**:",
                    "   - The engine draws in air and fuel.",
                    "",
                    "2. **Compression Stroke**:",
                    "   - The piston compresses the mixture.",
                    "",
                    "3. **Power Stroke**:",
                    "   - The spark plug ignites the mixture.",
                ]
            ),
        )

    def test_resets_each_section_after_heading(self):
        text = "\n".join(
            [
                "### First List",
                "1. Alpha",
                "1. Beta",
                "",
                "### Second List",
                "1. Gamma",
                "1. Delta",
            ]
        )

        self.assertEqual(
            normalize_ordered_list_numbering(text),
            "\n".join(
                [
                    "### First List",
                    "1. Alpha",
                    "2. Beta",
                    "",
                    "### Second List",
                    "1. Gamma",
                    "2. Delta",
                ]
            ),
        )

    def test_preserves_existing_start_number(self):
        text = "\n".join(
            [
                "4. Existing item",
                "1. Repeated item",
                "1. Another repeated item",
            ]
        )

        self.assertEqual(
            normalize_ordered_list_numbering(text),
            "\n".join(
                [
                    "4. Existing item",
                    "5. Repeated item",
                    "6. Another repeated item",
                ]
            ),
        )
