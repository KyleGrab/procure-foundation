"""
PROMPT-TEMPLATE-LOADER-R1: one shared, deterministic loader for the Markdown prompt files under
app/ai/prompts/. Each of those files carries a developer-documentation header, then a first
standalone `---` line, then the real runtime system-prompt body actually meant for the model.

Before this loader existed, negotiation_brief_service.py and contract_extraction_service.py each
read and `.format()`ed the *whole* file - so the model was also being sent the developer header,
and negotiation_brief.md's own header (which illustrates the mechanism with a literal
`{placeholder}` example) crashed outright at `.format()` time the moment a real caller reached it
(KeyError: 'placeholder' - NEGOTIATION-BRIEF-TEMPLATE-R1's investigation). This loader returns
only the body after the boundary; it never falls back to the whole file, silently or otherwise.
"""
from __future__ import annotations

import re

_PROMPT_DIR = "app/ai/prompts"

# A line that is exactly '---' (optional trailing whitespace) and nothing else - the same
# standalone-separator convention both existing prompt files already use to mark where their own
# developer documentation ends and the real runtime prompt begins.
_SEPARATOR_LINE = re.compile(r"^---[ \t]*$", re.MULTILINE)

# Known, application-owned template files only - callers pass one of these keys, never a path.
# Adding a new prompt file means adding one line here, not accepting an arbitrary path anywhere.
_KNOWN_TEMPLATES = {
    "negotiation_brief": "negotiation_brief.md",
    "contract_clause_extraction": "contract_clause_extraction.md",
}


class PromptTemplateBoundaryError(Exception):
    """Raised when a known template file doesn't have the expected developer-header/runtime-body
    shape (no standalone '---' boundary, or nothing left after it). Always a template-authoring
    bug, never something request input can trigger - deliberately a plain, clearly-named
    exception rather than a silent fallback to formatting or sending the whole file."""


def load_prompt_body(template_name: str) -> str:
    """Returns only the runtime body after the FIRST standalone '---' line in the named,
    known template file. The developer-documentation header above that line is discarded
    entirely - never read into the returned string, never formatted, never sent anywhere.

    template_name must be one of _KNOWN_TEMPLATES' own keys (never a caller-supplied path).
    Raises PromptTemplateBoundaryError if the template has no such boundary, or nothing left
    after it - never silently substitutes the whole file in either case.
    """
    try:
        filename = _KNOWN_TEMPLATES[template_name]
    except KeyError:
        raise PromptTemplateBoundaryError(
            f"Unknown prompt template name: {template_name!r} - expected one of "
            f"{sorted(_KNOWN_TEMPLATES)}"
        ) from None

    with open(f"{_PROMPT_DIR}/{filename}") as f:
        raw = f.read()

    match = _SEPARATOR_LINE.search(raw)
    if match is None:
        raise PromptTemplateBoundaryError(
            f"Prompt template {filename!r} has no standalone '---' line separating its developer "
            "header from its runtime body - refusing to guess or fall back to the whole file."
        )

    # Only the separator line itself and the one newline that ends it are removed - everything
    # else in the body (including the file's own blank line straight after the boundary, and any
    # later '---' line the body may itself contain) is preserved exactly as written.
    body_start = match.end()
    if body_start < len(raw) and raw[body_start] == "\n":
        body_start += 1
    body = raw[body_start:]

    if not body.strip():
        raise PromptTemplateBoundaryError(
            f"Prompt template {filename!r} has no runtime body after its '---' boundary line - "
            "refusing to send an empty prompt."
        )
    return body
