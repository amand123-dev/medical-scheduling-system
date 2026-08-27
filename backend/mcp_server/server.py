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
from datetime import datetime
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

from mcp_server import fhir

API_URL = os.environ.get("SCHEDULER_API_URL", "http://localhost:8000").rstrip("/")
API_TOKEN = os.environ.get("SCHEDULER_API_TOKEN", "")
API_USERNAME = os.environ.get("SCHEDULER_USERNAME", "")
API_PASSWORD = os.environ.get("SCHEDULER_PASSWORD", "")
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
        "denying, delaying or deprioritizing care based on a no-show score.\n\n"
        "The fhir_* tools read a SEPARATE external FHIR R4 server holding synthetic "
        "clinical records. FHIR resource ids are a different namespace from this "
        "practice's patient UUIDs — never pass one where the other is expected, and "
        "never assume a FHIR patient and a scheduler patient are the same person."
    ),
)


# Access tokens expire after an hour. An MCP server is long-lived and starts once,
# so a token pasted into the client config would stop working mid-session. When
# credentials are supplied the server logs in for itself and re-authenticates on
# the first 401, which keeps the client config durable.
_cached_token: str | None = API_TOKEN or None


async def _login() -> str:
    if not (API_USERNAME and API_PASSWORD):
        raise RuntimeError(
            "No usable credentials. Set SCHEDULER_USERNAME and SCHEDULER_PASSWORD "
            "(preferred -- the server then refreshes its own token), or set "
            "SCHEDULER_API_TOKEN to a token from POST /auth/login."
        )
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{API_URL}/auth/login",
            json={"username": API_USERNAME, "password": API_PASSWORD},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Login to {API_URL} failed ({resp.status_code}).")
    return resp.json()["access_token"]


async def _token() -> str:
    global _cached_token
    if _cached_token is None:
        _cached_token = await _login()
    return _cached_token


async def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {await _token()}"}


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    global _cached_token
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(f"{API_URL}{path}", params=params, headers=await _headers())
        if resp.status_code == 401 and API_USERNAME and API_PASSWORD:
            # Token expired mid-session: get a fresh one and retry exactly once.
            _cached_token = None
            resp = await client.get(f"{API_URL}{path}", params=params, headers=await _headers())
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


def _tz_offset_minutes(now: datetime | None = None) -> int:
    """
    A UTC offset in JavaScript's getTimezoneOffset() convention: minutes,
    positive west of UTC. The API expects that convention because the browser is
    its other caller. Defaults to this machine's current offset.
    """
    offset = (now or datetime.now().astimezone()).utcoffset()
    return 0 if offset is None else -int(offset.total_seconds() // 60)


@mcp.tool(
    description=(
        "Find the next open appointment slot for a provider and visit type. "
        "Slot length is derived from the visit type; do not pass a duration. "
        "Times are returned in UTC."
    )
)
async def find_next_available(
    provider_id: str,
    visit_type_id: str,
    tz_offset_minutes: int | None = None,
) -> dict:
    """
    Next bookable slot, honouring work hours, blocks and buffers.

    The practice's working hours are stored as bare hours (8 to 17) and mean
    local time. Without an offset the API reads them as UTC, which silently
    shifts the search window off the clinic's actual day -- it returns real
    empty slots, just ones nobody would ever book. Defaults to this machine's
    offset, matching what the browser sends.
    """
    return await _get(
        "/appointments/next-available",
        {
            "provider_id": provider_id,
            "visit_type_id": visit_type_id,
            "tz_offset": (_tz_offset_minutes() if tz_offset_minutes is None else tz_offset_minutes),
        },
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


# --- FHIR R4 tools ----------------------------------------------------------
#
# These read an external FHIR server, not this practice's database. They are a
# separate namespace on purpose: get_patient_context above is governed by the
# scheduler's role checks and writes identity_access_log, and none of that
# applies to a third-party API. Collapsing the two would quietly imply audit
# coverage that does not exist.


def _fhir_error(exc: fhir.FhirError) -> dict:
    kind = "scope_error" if isinstance(exc, fhir.ScopeError) else "fhir_error"
    return {"error": kind, "detail": str(exc)}


@mcp.tool(
    description=(
        "Report which FHIR R4 server is configured, its version, and which resource "
        "types are in scope. Call this first when a FHIR request fails, to tell a "
        "misconfigured base URL apart from a genuinely missing record."
    )
)
async def fhir_server_info() -> dict:
    """Capability summary of the configured FHIR R4 endpoint."""
    try:
        return await fhir.capability_summary()
    except fhir.FhirError as exc:
        return _fhir_error(exc)


@mcp.tool(
    description=(
        "Search patients on the external FHIR R4 server by name, family name or "
        "identifier. Returns synthetic test records — never real patients. These are "
        "FHIR ids, not this practice's patient UUIDs."
    )
)
async def fhir_search_patients(
    name: str | None = None,
    family: str | None = None,
    identifier: str | None = None,
    limit: int = 10,
) -> dict:
    """Find candidate FHIR patients."""
    try:
        return await fhir.search_patients(
            name=name, family=family, identifier=identifier, count=limit
        )
    except fhir.FhirError as exc:
        return _fhir_error(exc)


@mcp.tool(description="Fetch one FHIR R4 Patient resource by its FHIR id.")
async def fhir_get_patient(fhir_patient_id: str) -> dict:
    """Demographics for one FHIR patient."""
    try:
        return await fhir.get_patient(fhir_patient_id)
    except fhir.FhirError as exc:
        return _fhir_error(exc)


@mcp.tool(
    description=(
        "List a FHIR patient's Condition resources — diagnoses with clinical and "
        "verification status. Read-only reference data; do not use it to make "
        "clinical decisions or to alter how the patient is scheduled."
    )
)
async def fhir_get_conditions(fhir_patient_id: str, limit: int = 25) -> dict:
    """Conditions for one FHIR patient."""
    try:
        return await fhir.get_resources_for_patient("Condition", fhir_patient_id, count=limit)
    except fhir.FhirError as exc:
        return _fhir_error(exc)


@mcp.tool(
    description=(
        "List a FHIR patient's MedicationRequest resources. This is medication "
        "history for context only. Do not use it for controlled-substance "
        "monitoring, doctor-shopping detection, or any patient flagging — this "
        "system does not do clinical surveillance."
    )
)
async def fhir_get_medications(fhir_patient_id: str, limit: int = 25) -> dict:
    """Medication requests for one FHIR patient."""
    try:
        return await fhir.get_resources_for_patient(
            "MedicationRequest", fhir_patient_id, count=limit
        )
    except fhir.FhirError as exc:
        return _fhir_error(exc)


@mcp.tool(
    description=(
        "List a FHIR patient's Observation resources — vitals and lab results with "
        "values and units. Optionally filter by LOINC code or category "
        "(e.g. category='vital-signs')."
    )
)
async def fhir_get_observations(
    fhir_patient_id: str,
    code: str | None = None,
    category: str | None = None,
    limit: int = 25,
) -> dict:
    """Observations for one FHIR patient."""
    extra = {k: v for k, v in (("code", code), ("category", category)) if v}
    try:
        return await fhir.get_resources_for_patient(
            "Observation", fhir_patient_id, count=limit, extra=extra
        )
    except fhir.FhirError as exc:
        return _fhir_error(exc)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
