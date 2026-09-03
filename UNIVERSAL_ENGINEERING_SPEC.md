# System Rules & Architecture Spec

### Transferable Engineering Standards, Extracted from the NetDrop IQ Build

## 0. Purpose and How to Use This Document

This is not a spec for NetDrop IQ. NetDrop IQ's own domain logic — cost-to-serve formulas,
working capital cascades, quadrant classification — lives in `SPEC_dual_lens_architecture.md` and
stays with that project.

This document extracts the methodology: the standards, guardrails, and hard-won lessons that made
that build trustworthy, so they can seed a new project in a different domain. Paste the relevant
sections into a new project's system prompt, `CLAUDE.md`, or onboarding doc. Every rule here is
backed by a specific, real incident from the source project — not generic best-practice language
— because a rule with a story behind it is one an engineer (human or AI) actually remembers to
apply.

## 1. The Prime Directive

**Verify, don't assume. Measure, don't estimate. Test the real thing, not a description of the
real thing.**

Every other rule in this document is a specific application of this one idea. Where the source
project succeeded, it was usually because a claim got checked against actual execution before
being stated as fact. Where it stumbled, it was almost always because a plausible-sounding number
or behavior got repeated without that check — and every one of those stumbles was later caught,
corrected, and documented rather than left standing. That correction is the discipline working,
not a failure of it.

## 2. Core Architectural Standards

### 2.1 Separate pure logic from the presentation layer, always

Every calculation function should be callable and fully testable without the UI framework
installed or running. In this project, `calculate_cost_to_serve()` never called `st.*` anywhere in
its body — `render()` did, and nothing else. This paid off repeatedly:

- The entire regression suite could run in a bare Python environment with the UI framework mocked
  out.
- When Streamlit caching was added later, it could wrap the pure function in a thin decorated
  shell (`_cached_calculate_cost_to_serve()`) without touching the pure function at all — meaning
  every existing test kept working with zero modifications.
- When a correctness-critical function needed refactoring, the pure/UI split meant the refactor's
  blast radius was contained to one layer.

**Rule:** if a function's job is "compute a result," it should never import or call anything from
the UI layer. If its job is "display a result," it should do as little computation as possible
itself.

### 2.2 Grain safety — never silently join across data granularities

A recurring, load-bearing invariant: know exactly what one row represents (a drop, a SKU-day, a
customer) and never let a join silently duplicate or drop rows by mixing grains. Two concrete
disciplines that came out of this:

- **Row-count-in must equal row-count-out** for any transform that isn't an explicit aggregation.
  This was asserted directly, not just hoped for, across every field-availability combination in
  the working-capital module.
- When a value is structurally an enterprise-wide fact rather than something that varies per row
  (e.g., a distributor's own average payment terms to its suppliers), don't manufacture a fake
  per-row or per-customer version of it just to look more granular than the data supports.
  Broadcast it as a scalar and say so explicitly in the docstring. Manufactured granularity is a
  subtler data-integrity bug than a bad join, because it looks more trustworthy than it is.

### 2.3 Fallback hierarchies need an explicit, documented priority order

Whenever a value can be resolved multiple ways (a direct client figure, a computed/derived figure,
a generic default), the resolution order needs to be:

1. Explicit and centralized (one cascade, not the same logic re-derived in multiple places).
2. Documented with the reasoning for the order, not just the order itself.
3. Auditable after the fact — see §2.5 below. A fallback that fires silently is a liability even
   when the fallback value happens to be correct.

### 2.4 Config-driven constants, with typo protection built in

Numeric assumptions (rates, thresholds, sector-median defaults) belong in an external config file,
not hardcoded — but externalizing configuration creates a new failure mode: a typo'd key silently
fails to override anything, and the person editing the config has no idea their change did
nothing.

**Fix pattern:** on config load, scan for keys that don't match any known parameter, and suggest
the likely intended key via fuzzy string matching (Python's stdlib `difflib.get_close_matches`, no
new dependency) rather than silently ignoring the typo. Surface this as a visible warning, every
time the config loads, not just once.

### 2.5 Transparency by default — expose intermediate steps as their own outputs

A number that emerges from a multi-step calculation should let an auditor see which path it took,
not just the final figure. Two examples from this project:

- Every fallback-tier resolution got its own `_Source` column ("direct", "dynamic",
  "sector_median") alongside the resolved value — because the resolved value alone could not
  distinguish "a real client figure that happens to equal the generic default" from "the default
  fired." Both look identical as a number; only the source column tells you which happened. This
  was discovered as a genuine, previously-unresolvable ambiguity, not a hypothetical — a
  constructed test case proved a human auditor manually inspecting the raw output could not tell
  the two cases apart.
- Every allocation-hierarchy result got an `Allocation_Level_Used` column, so a consultant could
  see and explain why a given row cost what it cost, not just the number itself.

**Rule:** if a value could plausibly need defending in an audit or a client conversation, expose
the reasoning as a sibling column, not just a number.

### 2.6 Optional overlays must isolate cleanly from the baseline

When a feature is "an optional lens/mode layered on top of a baseline" (this project's Logistics
vs. Advanced Cost lens), keep a clean separation in the data model between "always computed" and
"computed only under the optional mode." This project always populated a `Baseline_*` column
regardless of which mode was active, specifically so that any future feature needing "the
baseline only, not the overlay" (a sensitivity-analysis lever, in this case) could read that one
column and automatically get correct behavior — with zero code changes — even for overlay
components added months later. This was tested and confirmed working exactly that way, three
separate times, as new overlay components were added.

### 2.7 One source of truth for repeated string/config literals

A string that means something specific (a mode name, a status label) and gets compared with `==`
in more than one place should be a single named constant, not independently retyped at each call
site. In this project, a single lens name was found hardcoded independently nine separate times
across two files before being consolidated — nine separate places a typo could have silently
broken a comparison with no error raised, since a string mismatch in an `==` check fails silently
(evaluates `False`) rather than raising.

## 3. Coding Guidelines

### 3.1 Vectorize; never loop over rows

No `.iterrows()`, no `.apply(axis=1)` on anything that could plausibly run at scale. Every
transform in this project's core engine was a vectorized pandas/numpy operation. This is both a
performance and a correctness discipline — vectorized code makes edge cases (all-zero, all-null,
single-row) mechanically consistent rather than requiring separate branches per row.

### 3.2 Handle division-by-zero and sign explicitly, don't let it happen by accident

Guard divisions with `np.where(denominator > 0, ..., fallback_value)` rather than letting a zero
produce `inf`/`NaN` that silently propagates.

Decide deliberately, case by case, whether `abs()` belongs in a calculation. In this project,
magnitude-based allocation logic used `abs()` because sign shouldn't affect how cost gets split,
while financial calculations (revenue, capital charges) never used `abs()`, because sign carries
real economic meaning there (a credit note, a capital credit) that clamping or absolute-valuing
would hide. Document which case applies and why, at the point of use — don't assume the reader
will infer it.

### 3.3 Function-length discipline, with a safe extraction method

A function that's grown past a few hundred lines across many incremental additions is a real
maintainability risk — but refactoring correctness-critical code is itself risky. The safe pattern
that worked repeatedly here:

1. Identify a genuinely self-contained block (reads a defined set of inputs, writes a defined set
   of outputs, doesn't share hidden state with the rest of the function beyond what's passed in).
2. Extract it as a mechanical lift — copy the exact code into a new, named function with a
   parameter list matching what it actually reads, and a docstring explaining what it does and why
   this extraction is claimed to be behavior-preserving.
3. Verify byte-for-byte identical output against the full existing test suite before considering
   it done. Not "the tests still pass" — confirm the exact same numeric results the pre-refactor
   code produced, ideally reproducing specific previously-verified decimal values, not just
   satisfying assertions in the abstract.

Two things NOT to do: don't rewrite logic while extracting it (extraction and improvement are
separate steps, done separately, so a bug can't hide behind "well I also improved it"), and don't
decompose the most tightly-coupled, highest-stakes part of a function just because you're on a
refactoring roll — some code earns the right to stay a little larger because breaking it apart
safely costs more than it's worth in that pass.

### 3.4 Comments explain why, especially for decisions that look wrong at first glance

The highest-value comments in this project were the ones defending a choice that a reasonable
reviewer might otherwise "fix" incorrectly — e.g., explicitly noting why a particular value stayed
unclamped when a similar-looking value elsewhere was deliberately floored at zero, with the
economic reasoning for the asymmetry stated inline. A comment that only restates what the code
does is close to worthless; a comment that preempts the next person's plausible mistake is not.

### 3.5 Long parameter lists are a real smell, but changing a public signature is a real risk — weigh both

A function that's accumulated fifteen-plus parameters across many incremental features is
genuinely harder to call correctly. The fix (bundling related parameters into a config object) is
well-understood — but changing a public function's signature touches every call site: every test,
every UI wiring, every consumer. In this project, that tradeoff was made explicitly and the wider
signature change was deliberately deferred rather than done reflexively, with the reasoning stated
plainly rather than silently skipped.

## 4. Security & Compliance Guardrails

### 4.1 Zero-persistence data handling, stated as an architectural constraint, not an afterthought

If the domain has a real data-protection requirement (this project's was POPIA-equivalent), that
requirement should shape the architecture from the start: all processing in-memory, nothing
written to disk, no external calls carrying client data. This is far cheaper to build in from day
one than to retrofit once the data model has drifted toward convenience.

### 4.2 Any user-controllable input that seeds a UI default must be validated and clamped before it reaches the widget

This project supported a "reproduce a saved scenario" state token — a user-editable, shareable
string that pre-fills every sidebar control. That's a direct injection surface: a malicious or
malformed token could otherwise set a negative threshold, an out-of-range percentage, or an
invalid mode string directly into a live widget.

**Fix pattern:** a `validate_and_clamp()` step that (a) drops any key it doesn't recognize, (b)
clamps every numeric field to a known-safe range, (c) explicitly rejects booleans posing as
numbers, and (d) rejects any string value not in an allow-list — run unconditionally before any
decoded value is ever passed as a widget's default. This was tested end-to-end through the actual
UI-rendering code path with deliberately adversarial inputs (negative thresholds, forged mode
strings), not just against the validation function in isolation.

### 4.3 Config integrity checks are a security-adjacent concern, not just a UX nicety

A silently-ignored typo in a cost-driver config (see §2.4) isn't just an annoyance — in a
financial-modeling context, it means a consultant's client-facing numbers are quietly wrong with
no error anywhere in the system. Treat "did my configuration change actually take effect" as
something the system proves to the user, not something the user has to trust.

## 5. Design System Rules

### 5.1 Progressive disclosure — don't show controls or warnings that don't apply to the current state

Widgets and warnings specific to an optional mode should only render when that mode is active. A
sidebar that shows every possible control regardless of relevance trains users to ignore the
sidebar.

### 5.2 Never fail silently — every invalid state either raises clearly or degrades visibly

Two acceptable outcomes for bad input: (a) a clear, specifically-worded exception that the caller
catches and surfaces as an actionable error message, or (b) an automatic, visible fallback with a
warning explaining what happened and why. Not acceptable: quietly producing a plausible-looking
wrong number. In this project, a negative classification-threshold input was made to raise rather
than silently produce a nonsensical result, with the calling UI code catching that specific
exception and falling back to a sensible default while telling the user what happened.

### 5.3 Presentation labels and internal storage names are separate, on purpose

Human-readable labels shown in a UI or exported document should never be the same string as an
internal column/field name. This project renamed several internal columns partway through the
build (for accuracy as understanding of the domain deepened) and it caused zero user-facing
disruption, because every exported label was already its own independent string, sourced from a
small, stable summary dict rather than derived from the column name directly.

## 6. Verification Discipline ("Learn Logic")

This is the section most worth carrying into a new project wholesale, because it's what actually
produced the trustworthiness of everything else.

### 6.1 A single measurement is not a measurement — it's an anecdote

Every meaningful performance or behavioral claim in this project that was checked with multiple
trials revealed variance that a single run would have hidden or misrepresented — sometimes
dramatically. One optimization appeared to make an operation slower in a first single-trial
measurement; a five-trial re-measurement showed the opposite was true, and the single-run result
was pure environment noise. **Rule:** before trusting a number, run it more than once. Report the
steady-state result, and say so explicitly when a first measurement gets overturned by more
careful re-measurement — don't quietly swap in the better number.

### 6.2 Reverse-engineer your own claims before presenting them as settled

After building something and believing it correct, actively try to find where the belief could be
wrong — not just confirm the happy path. In this project, this meant: checking a data-flow claim
by grepping every literal reference rather than trusting memory of "I think I checked this";
checking whether a stated architectural fact (e.g., "this only affects a single page") was
actually load-bearing on a deliberate design choice or merely incidental; and finding, through this
kind of self-audit, a materially more precise and important version of a claim that had been
stated too casually the first time (e.g., discovering that a "no page breaks" observation was
actually backed by a deliberate, riskier "no automatic page break exists at all" configuration — a
stronger and more consequential fact than originally stated).

### 6.3 Distinguish "confirmed" from "assumed," explicitly, in writing

Documentation should mark, in the text itself, which statements were directly tested and which are
inferred or expected-but-unverified. A reader shouldn't have to guess which claims in a spec
document carry real weight.

### 6.4 Correct your own record, plainly, when a past claim turns out wrong

A prior turn in this project reported a caching optimization as a "313x speedup." That number was
measured against a simplified test harness that didn't reflect the real underlying mechanism
(because the real mechanism wasn't installable in the working environment). Once that gap was
noticed, the real number was measured directly — approximately 3x, not 313x — and the correction
was written into the permanent project documentation explicitly, stating the original number, why
it was wrong, and what the real one is. A document that repeats an inflated number because
updating it feels awkward is worse than no document.

### 6.5 Fact-check the premise of a request before executing it

Not every framing handed to you is accurate, and complying with an inaccurate framing produces
confidently-wrong output. Recurring pattern in this project: a request would describe the system
in a way that didn't quite match its actual, verifiable behavior (a claimed feature that didn't
exist yet, an assumed architecture that didn't apply at this system's actual scale, a technical
claim about a caching mechanism that turned out to reflect a mocked test harness rather than the
real one). In every case, the more useful response was to check the premise against the real
system first and say plainly where it didn't hold — not to silently play along, and not to flatly
refuse either.

## 7. Risk Management Playbook

### 7.1 Negotiate scope explicitly before executing a large request

When a request bundles multiple substantial pieces of work, propose a sequence with reasoning
(what's lowest-risk, what's most load-bearing for the rest, what genuinely can't be verified in
the current environment) and get confirmation before executing everything in one uninterrupted
pass. This project repeatedly deferred large pieces of a request to their own turn, explained why,
and was consistently better off for it.

### 7.2 Escalate caution proportionally to a change's age, stakes, and blast radius

Not every change deserves the same ceremony. But when a change touches the oldest, most
heavily-tested, most financially-consequential logic in a system, the right response is more
verification than usual, not the standard amount: prototype the change in isolation first, test
every boundary condition you can think of (empty input, all-one-case input, the specific edge case
that would be hardest to get right) before it ever touches the real file, and only then apply it
to the real codebase.

### 7.3 The existing regression suite is the primary safety net for any refactor — treat it as such

A refactor is not "done" when it compiles. It's done when the full existing test suite reproduces
byte-identical results to before the change, and every named historical bug-fix test (not just
generic assertions) still reproduces its exact originally-verified values.

### 7.4 Defer irreversible actions for explicit human sign-off

File deletions, public API/signature changes, and similarly hard-to-undo actions get flagged with
evidence (e.g., "this file has zero references anywhere in the codebase, confirmed by search") and
left for the person to actually decide, even when the AI is confident the action is safe.
Confirmed-safe is not the same as authorized.

### 7.5 A confirmed technical infeasibility is a hard stop, not a workaround opportunity

If a proposed direction requires a tool, package, or environment that genuinely isn't available,
the right response is to say so plainly and explain what is achievable instead — not to write
untested code for the unavailable path and present it as though it were verified. In this project,
a proposed migration to different data-processing libraries was correctly declined specifically
because those libraries could not be installed in the working environment, and no amount of care
in writing that code would have made it verified. The energy went instead into a smaller, fully-
verifiable fix that addressed the same underlying measured problem.

## 8. Catalogued Loopholes & Fixes

A representative sample of real, specific defects found and fixed over the course of this project
— kept as a pattern library, since the same shapes of bug tend to recur in new domains even when
the specifics differ.

| Pattern | What went wrong | Fix |
|---|---|---|
| Sign-blind allocation | A cost-allocation formula didn't use `abs()`, so a negative value (a credit note/return) in a shared cost pool received a negative allocated cost instead of still bearing a fair share of real activity cost. | Use magnitude for allocation-basis calculations; sign only matters where it carries genuine financial meaning. |
| Partial-completeness silent degradation | When one row in a group had missing data needed for the "best" allocation method, only that one row silently fell back to a worse method — while its peers in the same group kept using data that was, in context, no longer trustworthy for the whole group. | Detect group-level completeness explicitly; if any member of a group is missing required data, the entire group falls back consistently, not just the affected row. |
| Boundary-condition matrix collapse | A user-configurable threshold, if set to a negative or otherwise invalid value, silently produced a degenerate result (e.g., every record landing in the same bucket) instead of an error. | Validate at the point of use; raise a specific, catchable exception with an actionable message; catch it one layer up and fall back to a safe default with a visible warning. |
| Silent config-typo swallow | A user-edited config file with a misspelled key silently discarded the user's intended override, with the system quietly using its old default instead. | Fuzzy-match unrecognized keys against known keys and surface a specific "did you mean X?" warning on every load. |
| Sub-threshold blind spot in a generic sanity check | A generic "is this column mostly clean" check only fired above a broad dirty-data percentage threshold — appropriate for catching "wrong column mapped entirely," but it meant a small number of dirty values in a column that gets summed (not averaged) could silently and proportionally understate a total, with nothing ever warning about it. | For fields where every dirty value directly and proportionally corrupts a downstream total, use a zero-tolerance warning threshold, separate from the broader "is this the wrong column" heuristic — and explain in the code why the two checks need different thresholds. |
| Indistinguishable fallback vs. coincidental match | A resolved value could come from either real input data or a generic fallback default — and when the real data happened to equal the default, the two cases were bit-for-bit identical in the output, with no way for even a careful human reviewer to tell them apart. | Add an explicit provenance/source column alongside every fallback-resolved value, driven by the exact same condition logic as the value resolution itself (so the two can't drift out of sync). |
| Decorator-evaluation-time surprise | Adding a caching decorator to a function broke every test that imported the containing module with a minimal mock of the underlying framework — because the decorator gets evaluated at import time, not when the decorated function is actually called, and the minimal mock didn't implement the decorator's real interface. | When introducing a new decorator with side effects at import time, audit every place that imports the module under test with a mocked dependency, not just the specific new function's own tests. |
| Unbounded cache growth, discovered as a follow-on risk of a prior fix | A caching fix (correctly) eliminated redundant recomputation — but the caching mechanism's real-world default has no automatic eviction and is shared across all concurrent users of a deployed system, not scoped per session. Measured directly: a realistic session could accumulate multiple gigabytes of cached data with nothing ever freeing it. | Explicitly bound cache size and/or time-to-live, sized to the measured footprint of what's actually being cached — not a default guess — and re-verify the fix didn't break the caching behavior itself. |
| Quadratic/superlinear cost from an unnecessary uniqueness explosion | A grouping operation used a synthetic unique-per-row key for records that had no real group identifier, so that unrelated ungrouped records wouldn't be silently merged together — but this meant a dataset with mostly-ungrouped records forced an expensive general-purpose grouping algorithm to process hundreds of thousands of trivial single-member groups, when the correct answer for each of those groups was analytically obvious without any grouping computation at all. | Split the computation: run the real grouping algorithm only over the subset that has genuine group identifiers (a much smaller key space), and fill in the analytically-known trivial result directly for everything else — proven exactly equivalent to the original computation via targeted before/after comparison across every boundary case, not assumed equivalent from the logic alone. |

## 9. Tools Built to Overcome Human Error

Concrete, reusable mechanisms — not general advice, but specific things that were actually built:

- **Fuzzy-match config key suggestions** (§2.4) — turns a silent typo into a visible, specific,
  correctable warning.
- **Provenance/source tracking columns** (§2.5) — turns an unresolvable ambiguity into a
  directly-inspectable fact.
- **Validate-and-clamp on every externally-supplied state input** (§4.2) — makes a malformed or
  malicious saved-state string harmless by construction, rather than relying on every downstream
  consumer to individually defend itself.
- **Grain-safety assertions as a running invariant** (§2.2) — "row count in equals row count out"
  is cheap to check and catches an entire category of silent data-corruption bug immediately.
- **Self-reporting generator scripts** — a script that creates synthetic data for testing should
  also print evidence, computed from its own actual output, that the data has the properties it
  claims to have (a specific split across categories, a specific set of edge cases represented) —
  rather than trusting that the generation logic did what it was intended to do. This caught real
  generator bugs on more than one occasion in this project, where the intended data distribution
  and the actual one had quietly diverged.
- **Named, reproducible historical test fixtures** — every previously-found bug got a small,
  permanent, exactly-reproducing test case, so future changes are checked not just against generic
  correctness but against the specific historically-wrong behavior never recurring.

## 10. Recurring Failure Patterns & Standing Solutions

Patterns that came up more than once across this project, and the standing response that was
settled on:

| Recurring situation | Standing solution |
|---|---|
| A dependency needed for full testing isn't installed in the working environment, and can't be installed (no network access). | State this plainly as a hard limitation, don't write untested code for that path and imply it's verified, and clearly identify what can be tested as an alternative that addresses the same real, underlying concern. |
| A single timing/behavioral measurement looks surprising or supports a nice conclusion. | Re-run it multiple times before trusting it; report the steady-state result; explicitly flag when a more careful re-measurement overturned an earlier one. |
| A large request bundles several substantial pieces of work. | Propose a sequenced plan with reasoning; get confirmation on the sequence rather than silently executing everything in one pass. |
| A change touches old, heavily-tested, high-stakes logic. | Prototype in isolation first; test every boundary condition against the literal prior behavior before touching the real file; treat the existing regression suite as the thing that has to stay byte-identical. |
| A prior claim, on closer inspection, turns out to be wrong or overstated. | Correct it explicitly, in writing, in the permanent record — state what was originally claimed, why it was wrong, and what the real figure or fact is. |
| A request's framing doesn't quite match the system's actual, verifiable behavior. | Check the premise against reality before proceeding; state plainly where it doesn't hold; don't silently comply with an inaccurate framing. |

## 11. Effective Prompt Patterns

Patterns in how requests were framed that reliably produced rigorous, well-scoped work — worth
reusing when seeding a new project:

- **Role framing that invokes a specific standard of rigor:** "Act as a senior [X]
  engineer/tutor/analyst reviewing this," rather than a generic "improve this" — this reliably
  produced more structured, more skeptical, more thorough engagement than an unframed request.
- **Pairing "improve X" with an explicit non-goal:** "optimize/refactor this — do not change
  existing functionality" is a much safer instruction than "optimize this" alone, because it gives
  an unambiguous, checkable success criterion (byte-identical output) rather than leaving
  "improved" open to interpretation.
- **Explicitly asking for self-skepticism:** "audit this end to end, use reverse engineering to
  verify yourself" produced a materially different (and better) result than asking for
  confirmation of prior work, because it explicitly authorized treating the prior claim as a
  hypothesis rather than a settled fact.
- **Requesting a plan before implementation on large asks:** asking for a breakdown and reasoning
  before code gets written surfaces scope and sequencing disagreements while they're still cheap
  to resolve.
- **Granting explicit conditional permission:** "continue if logical, safe, mathematical, and
  warranted" is more useful than either an unconditional go-ahead or a request for another round
  of confirmation — it hands over the judgment call explicitly, with named criteria, rather than
  either removing judgment from the loop or blocking on another round-trip.
- **Asking "where should we focus next"** rather than assigning the next task directly — this
  surfaces the assistant's own honest assessment of priority (including, correctly, an assessment
  of what can't currently be verified) before committing effort to a direction.

## 12. Quick-Start Checklist for a New Project

- [ ] Establish the pure-logic / presentation-layer split before writing the first real feature,
      not after.
- [ ] Decide the data-protection/compliance constraints up front; let them shape the architecture,
      not retrofit them later.
- [ ] Put every "assumption" numeric constant in an external config, with typo detection on load.
- [ ] For every fallback/multi-tier resolution, plan the provenance-tracking column at design time,
      not as an afterthought once the ambiguity is discovered the hard way.
- [ ] Decide, and write down, whether a `max_entries`/`ttl`-equivalent bound is needed on any
      caching layer before it's added, sized to a real measured footprint, not a guess.
- [ ] Build a small set of named, permanent regression fixtures for every bug found — never
      fixed-and-forgotten.
- [ ] When something can't be verified in the current environment, say so in the documentation
      itself, not just in conversation.
- [ ] Revisit this document's §8–§10 periodically as the new project accumulates its own
      catalogued loopholes and standing solutions — the value of this kind of document compounds
      the more real incidents it accumulates.
