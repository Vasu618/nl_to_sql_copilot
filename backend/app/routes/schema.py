"""
/schema endpoint — returns live DB schema for the frontend sidebar.

This is the only endpoint in Week 1. Week 2 adds /ask; Week 3 adds /history.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter

from ..schema_context import get_schema


router = APIRouter()


@router.get("/schema")
def schema() -> dict[str, Any]:
    """Return live schema: tables, columns, types, FKs, and 3 sample rows each.

    The frontend renders this in the sidebar so users can see what they can
    ask about. The same metadata feeds the LLM prompt (Week 2) and the
    validator (Week 2) — single source of truth.
    """
    tables = get_schema()
    return {
        "tables": [
            {
                "name": t.name,
                "columns": [asdict(c) for c in t.columns],
                "sample_rows": t.sample_rows,
            }
            for t in tables
        ]
    }
