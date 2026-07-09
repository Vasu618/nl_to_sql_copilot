"""
FastAPI application entry point.

Run locally with:
    cd backend
    .venv/bin/uvicorn app.main:app --reload --port 8000

Endpoints (Week 1):
    GET  /           — health check
    GET  /schema     — live DB schema (tables, columns, types, FKs, sample rows)

Week 2 will add:
    POST /ask        — full NL -> SQL -> validated -> executed -> explained pipeline
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routes import ask as ask_route
from .routes import schema as schema_route


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Converts plain-English business questions into validated, safety-checked "
        "SQL with a self-correction loop. See docs/architecture.md."
    ),
)

# CORS — locked down to specific origins in production. For local dev, allow
# the Next.js dev server on its default port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js dev server
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/")
def health() -> dict[str, str]:
    """Health check."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": "0.1.0",
        "llm_provider": settings.llm_provider,
    }


app.include_router(schema_route.router, tags=["schema"])
app.include_router(ask_route.router, tags=["ask"])
