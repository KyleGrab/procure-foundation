# ProcureIQ — Security Model

## 1. Identity & sessions

- Passwords hashed with **Argon2id** (`app/core/security.py`), never bcrypt/sha — Argon2id is the current
  OWASP recommendation and resists GPU cracking better at equivalent cost settings.
- JWT access token: short-lived (15 min), claims limited to `sub` (user id), `active_org_id`, `role`,
  `iat`, `exp`. **Deliberately excludes** the user's full list of org memberships — see 3.1 below.
- JWT refresh token: longer-lived (14 days), stored hashed server-side (rotation on use — reuse of an old
  refresh token revokes the whole family, standard refresh-token-rotation practice).
- MFA: TOTP, optional per user, enforceable per organisation via `organisation_settings`.

## 2. RBAC

Roles: `owner, admin, executive, finance, procurement_manager, buyer, operations, analyst, consultant,
viewer`. Permissions are granular capabilities (`upload_data, delete_datasets, view_financials,
edit_suppliers, approve_opportunities, configure_integrations, view_contracts, manage_users,
generate_reports, access_ai, export_data, approve_price_increases, approve_savings`) mapped to roles in
`app/core/permissions.py`, resolved as a dependency (`require_permission("edit_suppliers")`) injected into
every mutating route — checked in the service layer, not hidden by the frontend. Spec Section 8 says this
explicitly and it's non-negotiable: frontend hiding a button is UX, not security.

## 3. Tenant isolation — defense in depth

Two independent layers, because one layer failing should not equal a breach:

1. **Application layer** — every repository/service method takes `organisation_id` explicitly (usually
   from a `CurrentOrg` dependency, never from client input) and includes it in the query. Code review and
   the automated cross-tenant test suite (Section 67 of the spec) catch regressions here.
2. **Database layer (Postgres RLS)** — every tenant-scoped table has `ENABLE` *and* `FORCE ROW LEVEL
   SECURITY`, with a policy against `current_setting('app.current_org_id')`, set once per request from
   the validated token. The application connects as `procureiq_app`, a role with only DML grants and
   never table ownership (migration 0004). Even if (1) is bypassed by a bug, the database itself refuses
   to return another tenant's rows to that connection.

**This second layer was not actually working from Phase 1 through Phase 3.** `ENABLE ROW LEVEL SECURITY`
alone does not bind to a table's owner, and the application connected with the same role that owned every
table — meaning RLS policies existed but did not constrain the app's own queries. Found while writing the
RLS integration test suite (`backend/tests/test_rls_integration.py`) and fixed in migration 0004 —
see `docs/decisions/ADR-011-least-privilege-role-force-rls.md` for the full account and
`docs/deployment-rls-checklist.md` for how to verify both conditions hold in any environment.

RLS is the layer that makes "we tested for it" into "the database physically won't do it" — but only once
both `ENABLE` and `FORCE` are true and the connecting role doesn't own the tables. Given the product
is *entirely* about handling other companies' confidential pricing, this is the one place in the whole spec
where the extra implementation cost is not optional, and the one place worth re-verifying directly rather
than trusting that a migration ran cleanly once.

### 3.1 The consultant multi-org threat specifically

Section 4.6 requires consultants to belong to multiple client organisations. This is the single highest-risk
identity scenario in the product: a user who is *supposed* to have access to org A and org B, but never both
at once in the same request context.

Chosen model: the JWT carries exactly one `active_org_id`. Switching organisations (`POST
/auth/switch-org`) validates the target membership is `active`, issues a **new** token, and the old token
remains valid only for its original `active_org_id` until it expires (15 min). There is no client-side
"which org am I acting as" state that isn't backed by a freshly issued, server-validated token. This means
a stolen/replayed token is scoped to one org, and org-switching is always an auditable, explicit event
(logged to `audit_logs` with `action = 'org_context_switch'`).

## 4. File upload security

MIME type and extension validated server-side (not trusted from the client), size-limited per org tier,
stored under randomized keys (`{org_id}/{uuid}.{ext}`) — original filenames never used as storage paths.
Files are never executed; PDF/XLSX parsing happens in sandboxed worker processes with resource limits.

## 5. AI-specific security

- LLM calls never receive raw unrestricted database dumps — only the pre-computed structured result of a
  permission-checked analytics function (Section 37's pipeline, enforced literally in code, not just
  described in a doc).
- Per-tenant data is never used to fine-tune or improve a shared/public model without explicit contractual
  consent, and that consent is a field on `organisations`, not an assumption.
- AI extraction (contracts) writes only to a staging table (`contract_extractions`) that nothing
  calculation-facing reads from until a human sets `verification_status = 'human_verified'` — see
  `data-model.md` ADR-004. This is a security control as much as a data-quality one: it's the boundary that
  stops a manipulated or hallucinated contract term from silently becoming a rebate the company pays out.

## 6. Secrets & transport

TLS everywhere in production. Secrets via environment variables only (`.env` never committed — see
`.gitignore`). No secret ever appears in `audit_logs.metadata` or application logs (structured JSON logging
with an explicit denylist of field names: `password`, `token`, `access_key`, `secret_key`).

## 7. Rate limiting

Applied at the Redis layer to: `/auth/login`, `/auth/password-reset/*`, `/ai/*`, `/imports` (upload
endpoints). Limits are per-IP and per-account, not just per-IP, since credential-stuffing and account-level
abuse need different defenses.

## 8. What this does *not* claim

Architecture supports POPIA-aligned operational controls (tenant isolation, access control, audit trails,
retention configuration, deletion workflows, encryption in transit and at rest). It does not constitute
legal compliance advice — that requires a qualified privacy/legal professional reviewing the actual deployed
system and the organisation's specific data-processing activities.
