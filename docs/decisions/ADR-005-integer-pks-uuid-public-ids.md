# ADR-005: BIGINT identity primary keys, UUIDv7 public ids

**Status:** Accepted (deviates from spec's "UUID primary keys" instruction)

**Context:** Spec section 9 asks for UUID primary keys throughout. At the row counts targeted in section 60
(millions of invoice/purchase rows), random UUIDv4 as a clustered index key causes write amplification and
index bloat — every insert lands in a random b-tree leaf instead of the tail.

**Decision:** Internal PK is `BIGINT GENERATED ALWAYS AS IDENTITY`. A separate `public_id UUID NOT NULL
DEFAULT uuidv7()` column is unique-indexed and is the only identifier ever exposed over the API — UUIDv7 is
time-ordered so it keeps most of the index-locality benefit of a sequential key while still being
non-enumerable externally (satisfies the reason you'd want UUIDs over the wire in the first place).

**Consequences:** One extra column + index per table versus the spec's literal instruction; meaningfully
better write throughput and index size at the scale the spec itself targets.
