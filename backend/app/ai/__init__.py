"""
LLMProvider abstraction - brought forward from Phase 6 specifically for the negotiation brief
(spec Section 26), which this addendum spec requires in Phase 2. Scope stays narrow: this is the
provider interface and one prompt, not the general copilot/permission-aware query pipeline from
docs/architecture.md section 1 - that full pipeline is still Phase 6. No network in this sandbox
means nothing here has ever actually called a model - see negotiation_brief_service.py's docstring.
"""
