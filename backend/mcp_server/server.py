"""
MCP server for SmallPractice Scheduler.

Exposes the scheduler as tools an LLM client (Claude Desktop, Claude Code) can
call. The server holds no business logic — every tool is a thin adapter over
the HTTP API, so the matcher, the risk scorer and the audit rules stay in one
place and the agent inherits exactly the permissions of the token it was given.

That last point is the design: an MCP client is just another API consumer. It
authenticates as a staff user, it is bound by that user's role, and its
patient-scoped reads land in identity_access_log like anyone else's. There is
no back door to the database.

Run with:  python -m mcp_server.server
Configure via SCHEDULER_API_URL and SCHEDULER_API_TOKEN.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

API_URL = os.environ.get("SCHEDULER_API_URL", "http://localhost:8000").rstrip("/")
API_TOKEN = os.environ.get("SCHEDULER_API_TOKEN", "")
TIMEOUT = float(os.environ.get("SCHEDULER_API_TIMEOUT", "30"))

mcp = MCPServer(
    name="smallpractice-scheduler",
    title="SmallPractice Scheduler",
    instructions=(
        "Tools for a small medical practice's appointment scheduler.\n\n"
        "Patients are identified by UUID, never by name. Operational data "
        "contains no PHI by design. Do not ask for or infer patient names; if a "
        "user needs a name, direct them to the audited lookup in the web UI.\n\n"
        "get_patient_context reads that patient's clinical documents and is "
        "recorded in the practice's identity access log. Call it only when the "
        "user's request actually requires it, and tell them it was logged.\n\n"
        "Risk scores drive outreach, not deprioritization. Never suggest "
        "denying, delaying or deprioritizing care based on a no-show score."
    ),
)


def _headers() -> dict[str, str]:
    if not API_TOKEN:
        raise RuntimeError(
            "SCHEDULER_API_TOKEN is not set. Obtain a staff token from POST /auth/login "
            "and export it before starting the MCP server."
        )
    return {"Authorization": f"Bearer {API_TOKEN}"}


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(f"{API_URL}{path}", params=params, headers=_headers())
    if resp.status_code == 403:
        return {
            "error": "forbidden",
            "detail": "The configured staff token lacks the required role.",
        }
    if resp.status_code == 404:
        return {"error": "not_found", "detail": resp.json().get("detail", "")}
    resp.raise_for_status()
    return resp.json()


@mcp.tool(
    description=(
        "Search the practice's protocol and policy documents — visit durations, "
        "follow-up windows, waitlist rules, patient prep instructions. Contains no "
        "patient data. Returns passages with their source document for citation."
    )
)
async def search_protocols(query: str, limit: int = 5) -> dict:
    """Retrieve clinic protocol passages relevant to a question."""
    return await _get("/rag/protocols/search", {"q": query, "k": limit})


@mcp.tool(
    description=(
        "Retrieve passages from one patient's visit documents, identified by UUID. "
        "AUDITED: every call writes a row to the practice's identity access log. "
        "Requires admin or provider role. Returns de-identified text."
    )
)
async def get_patient_context(patient_uuid: str, query: str, limit: int = 5) -> dict:
    """Retrieve a patient's document passages. This access is logged."""
    return await _get(f"/rag/patients/{patient_uuid}/context", {"q": query, "k": limit})


@mcp.tool(
    description=(
        "Find the next open appointment slot for a provider and visit type. "
        "Slot length is derived from the visit type; do not pass a duration."
    )
)
async def find_next_available(provider_id: str, visit_type_id: str) -> dict:
    """Next bookable slot, honouring work hours, blocks and buffers."""
    return await _get(
        "/appointments/next-available",
        {"provider_id": provider_id, "visit_type_id": visit_type_id},
    )


@mcp.tool(description="List the practice's providers, with specialty and active status.")
async def list_providers() -> Any:
    """All providers."""
    return await _get("/providers")


@mcp.tool(description="List visit types with their durations and new-patient flags.")
async def list_visit_types() -> Any:
    """All visit types."""
    return await _get("/visit-types")


@mcp.tool(
    description=(
        "Show the current waitlist as ranked entries. Each entry carries a patient "
        "UUID, priority, how long they have waited, and offer status — never a name."
    )
)
async def list_waitlist(provider_id: str | None = None) -> Any:
    """Waitlist entries, optionally filtered to one provider."""
    params = {"provider_id": provider_id} if provider_id else None
    return await _get("/waitlist", params)


@mcp.tool(
    description=(
        "Get a patient's no-show risk score and bucket by UUID. Returns "
        "'insufficient_data' below three prior appointments. This signal escalates "
        "reminder outreach; it must not be used to deprioritize or deny care."
    )
)
async def get_no_show_risk(patient_uuid: str) -> dict:
    """No-show risk for one patient."""
    return await _get(f"/scorer/risk/{patient_uuid}")


@mcp.tool(
    description=(
        "Practice dashboard metrics over a trailing window: fill rate, no-show rate, "
        "and slots recovered by the waitlist backfill engine."
    )
)
async def get_dashboard_metrics(days: int = 30) -> dict:
    """Aggregate practice metrics. No patient-level data."""
    return await _get("/dashboard/metrics", {"days": days})


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
