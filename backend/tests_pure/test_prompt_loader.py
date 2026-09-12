"""
PROMPT-TEMPLATE-LOADER-R1: pure tests for app.ai.prompt_loader - no DB, no FastAPI, no network,
runnable via plain unittest (app.ai.prompt_loader itself imports nothing but `re`, matching the
§2.1 boundary CLAUDE.md requires for backend/app/ai/).
"""
import os
import tempfile
import unittest

from app.ai import prompt_loader
from app.ai.prompt_loader import PromptTemplateBoundaryError, load_prompt_body


class TestRealTemplatesLoadCleanly(unittest.TestCase):
    """Against the actual, committed prompt files - proves the real defect is fixed, not just a
    synthetic case."""

    def test_negotiation_brief_loads_and_excludes_the_literal_placeholder_header_text(self):
        body = load_prompt_body("negotiation_brief")
        # The header's own illustrative example - if this leaked through, .format() would raise
        # KeyError: 'placeholder' exactly as it used to (NEGOTIATION-BRIEF-TEMPLATE-R1).
        self.assertNotIn("{placeholder}", body)
        self.assertNotIn("negotiation_brief_service.generate_brief", body)  # dev-only header text
        # The real runtime substitutions are still present, untouched.
        for token in (
            "{supplier_name}", "{annual_spend}", "{weighted_increase_pct}", "{total_annual_impact}",
            "{top_sku_impacts}", "{negotiation_targets}", "{supplier_performance_or_none}",
        ):
            self.assertIn(token, body)
        # The real second-person runtime prompt survived.
        self.assertIn("You are helping a South African food-distribution procurement team", body)

    def test_contract_clause_extraction_loads_and_excludes_its_developer_header(self):
        body = load_prompt_body("contract_clause_extraction")
        self.assertNotIn("contract_extraction_service.extract_terms", body)  # dev-only header text
        self.assertIn("{document_text}", body)
        self.assertIn("You are extracting structured contract terms", body)


class TestBoundaryContractWithSyntheticTemplates(unittest.TestCase):
    """Exercises the loader's own contract precisely, independent of the real prompt files'
    current content - a future edit to either real file can't accidentally stop testing these
    rules."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_dir = prompt_loader._PROMPT_DIR
        self._orig_known = dict(prompt_loader._KNOWN_TEMPLATES)
        prompt_loader._PROMPT_DIR = self._tmpdir.name

    def tearDown(self):
        prompt_loader._PROMPT_DIR = self._orig_dir
        prompt_loader._KNOWN_TEMPLATES = self._orig_known
        self._tmpdir.cleanup()

    def _write(self, filename: str, content: str) -> None:
        with open(os.path.join(self._tmpdir.name, filename), "w") as f:
            f.write(content)

    def test_first_standalone_separator_is_honoured(self):
        self._write(
            "synthetic.md",
            "# Header\n\nSome dev notes with a brace example {like_this}.\n\n---\n\nReal body: {value}\n",
        )
        prompt_loader._KNOWN_TEMPLATES = {"synthetic": "synthetic.md"}
        body = load_prompt_body("synthetic")
        self.assertNotIn("{like_this}", body)
        self.assertNotIn("Header", body)
        self.assertNotIn("dev notes", body)
        self.assertIn("Real body: {value}", body)

    def test_later_separators_inside_the_body_do_not_truncate_it(self):
        self._write(
            "synthetic.md",
            "# Header\n\n---\n\nReal body starts here.\n\n---\n\nMore real body after a second "
            "separator - a horizontal rule the model's own output guidance is allowed to use.\n",
        )
        prompt_loader._KNOWN_TEMPLATES = {"synthetic": "synthetic.md"}
        body = load_prompt_body("synthetic")
        self.assertIn("Real body starts here.", body)
        self.assertIn("More real body after a second separator", body)

    def test_leading_separator_newline_only_is_removed_rest_of_body_untouched(self):
        # Two blank lines between the boundary and the real body (matching neither real file
        # exactly, deliberately more than one, to prove only ONE newline - the separator line's
        # own line ending - is ever removed, not every blank line that follows it).
        self._write("synthetic.md", "Header.\n---\n\n\nReal body with leading blank lines preserved.\n")
        prompt_loader._KNOWN_TEMPLATES = {"synthetic": "synthetic.md"}
        body = load_prompt_body("synthetic")
        self.assertEqual(body, "\n\nReal body with leading blank lines preserved.\n")

    def test_non_standalone_dashes_are_not_treated_as_the_boundary(self):
        self._write(
            "synthetic.md",
            "Header mentions a range like 10---20 inline, and a code fence:\n```\nx = 1---2\n```\n"
            "\n---\n\nReal body: {value}\n",
        )
        prompt_loader._KNOWN_TEMPLATES = {"synthetic": "synthetic.md"}
        body = load_prompt_body("synthetic")
        self.assertIn("Real body: {value}", body)
        self.assertNotIn("Header mentions", body)

    def test_missing_boundary_raises_clearly_and_does_not_return_the_whole_file(self):
        self._write("synthetic.md", "Just a header, no boundary at all.\n")
        prompt_loader._KNOWN_TEMPLATES = {"synthetic": "synthetic.md"}
        with self.assertRaises(PromptTemplateBoundaryError):
            load_prompt_body("synthetic")

    def test_empty_body_after_boundary_raises_clearly(self):
        self._write("synthetic.md", "Header.\n\n---\n\n   \n")
        prompt_loader._KNOWN_TEMPLATES = {"synthetic": "synthetic.md"}
        with self.assertRaises(PromptTemplateBoundaryError):
            load_prompt_body("synthetic")

    def test_unknown_template_name_raises_clearly_not_an_arbitrary_path_read(self):
        prompt_loader._KNOWN_TEMPLATES = {"synthetic": "synthetic.md"}
        with self.assertRaises(PromptTemplateBoundaryError):
            load_prompt_body("../../etc/passwd")


if __name__ == "__main__":
    unittest.main()
