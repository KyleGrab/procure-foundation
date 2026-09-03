# ADR-004: AI-extracted contract terms are staged, never consumed directly

**Status:** Accepted

**Context:** Spec section 78 prohibits AI fabricating financial values; section 31 requires human
verification status on extracted contract terms; sections 29/41 have rebates and negotiation prep consuming
contract terms. As specified, nothing stops a calculation from reading an unverified extraction.

**Decision:** LLM contract extraction writes only to `contract_extractions` (staging). No
calculation-facing table (`rebates`, `opportunities`, negotiation-prep inputs) ever reads from that table.
Promotion to `contracts`' verified fields requires `verification_status = 'human_verified'`, set by an
explicit human action that is itself an audited event.

**Consequences:** Extra table and an explicit promotion step in the contract-upload UX (Phase 7). The
alternative — verification status as a flag on the same row calculations already read — is one missed check
away from the exact fabrication risk section 78 was written to prevent.
