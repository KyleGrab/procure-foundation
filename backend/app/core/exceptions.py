"""
Structured application exceptions -> structured API error responses (spec Section 53).
Never let a raw exception/stack trace reach a production response body.
"""
from __future__ import annotations


class ProcureIQError(Exception):
    """Base class. code is a stable machine-readable string, message is human-readable."""

    code: str = "internal_error"
    status_code: int = 500

    def __init__(self, message: str, details: list[dict] | None = None) -> None:
        self.message = message
        self.details = details or []
        super().__init__(message)


class NotFoundError(ProcureIQError):
    code = "not_found"
    status_code = 404


class ValidationFailedError(ProcureIQError):
    code = "validation_failed"
    status_code = 422


class AuthenticationError(ProcureIQError):
    code = "authentication_failed"
    status_code = 401


class PermissionDeniedError(ProcureIQError):
    code = "permission_denied"
    status_code = 403


class ConflictError(ProcureIQError):
    code = "conflict"
    status_code = 409


class EvidenceRequiredError(ProcureIQError):
    """
    F-03: raised when an endpoint would otherwise present caller-supplied financial input as an
    evidenced result. Distinct code from ValidationFailedError deliberately - the request isn't
    malformed, the system genuinely lacks the evidence infrastructure to process it yet. A client
    needs to be able to tell these two failure modes apart.
    """

    code = "evidence_required"
    status_code = 422


class RegistrationDisabledError(ProcureIQError):
    """
    D-01: raised before any organisation or user is created when settings.allow_self_registration
    is False - a controlled demo environment's way of closing public self-registration without
    touching login, which is a structurally separate code path (see auth_service.login vs
    auth_service.register - independent functions, no shared logic beyond both taking a db
    session). 403, not 422 - the request isn't malformed, the operation itself is disallowed.
    """

    code = "registration_disabled"
    status_code = 403


class InvalidImportFileError(ProcureIQError):
    code = "invalid_import_file"
    status_code = 422


class InvalidAuditIdentifierError(ProcureIQError):
    """
    AUDIT-ENTITY-ID-R2: raised by app.services.audit_service.record when entity_id is none of
    its supported types (str, int, uuid.UUID, or None). Always an internal-caller bug, never
    something real request input can trigger directly (no route accepts an arbitrary entity_id
    from a client) - 500, not a 4xx, matching that distinction. Deliberately narrow rather than a
    blanket str(anything): a caller passing e.g. a whole ORM object or a dict here almost always
    means a real mistake (the wrong variable, an unresolved object instead of its id) that a
    permissive str() would silently paper over as some unhelpful repr() text instead of failing
    where the mistake actually is.
    """

    code = "invalid_audit_identifier"
    status_code = 500


class DatabaseUnavailableError(ProcureIQError):
    """
    A real, previously-unhandled gap: a Postgres connection/transaction failure inside get_db
    (session open, or the SET LOCAL app.current_org_id call itself) would otherwise propagate as
    a raw, unhandled SQLAlchemyError - no clean status code, no structured response body, and a
    stack trace potentially reaching the client. 503, not 500: this is specifically "a dependency
    is down," a meaningfully different, more actionable signal than "the application itself
    errored." General to every route through get_db, not canvas-specific - every route that
    touches tenant-scoped data shares this one session dependency.
    """
    code = "database_unavailable"
    status_code = 503
