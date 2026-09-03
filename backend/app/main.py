from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import ProcureIQError
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    """
    D-01: app construction moved into a factory function - the smallest clean change needed to
    make ENABLE_API_DOCS genuinely testable. Before this, `app = FastAPI(...)` at module level
    baked settings.enable_api_docs's value into docs_url/openapi_url exactly once, at import
    time - a test setting the env var afterward and clearing get_settings()'s cache could never
    affect anything, since the already-constructed FastAPI object never re-reads it. Calling
    create_app() fresh, with a different env var value already set beforehand, produces a
    genuinely different app instance - real, not simulated.

    The module-level `app = create_app()` below preserves `uvicorn app.main:app` exactly as
    before - this is a structural change to allow re-construction on demand, not a behavior
    change to normal running.
    """
    settings = get_settings()
    configure_logging()

    app = FastAPI(
        title=settings.branding_app_name,
        version="0.1.0",
        # D-01: both None when disabled, FastAPI's own supported mechanism for turning the route
        # off entirely (a real 404, not an error) - the application's actual configured paths,
        # not separately-hardcoded ones that could drift from what's really being served.
        docs_url="/api/v1/docs" if settings.enable_api_docs else None,
        openapi_url="/api/v1/openapi.json" if settings.enable_api_docs else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ProcureIQError)
    async def procureiq_error_handler(request: Request, exc: ProcureIQError) -> JSONResponse:
        # Structured error envelope per spec Section 53 - the only shape of error body the
        # frontend ever needs to handle. Never leaks a stack trace to the client.
        request_id = request.headers.get("x-request-id", "")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id,
                }
            },
        )

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
