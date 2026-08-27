"""
FHIR R4 client for the MCP server.

Talks to any FHIR R4 base URL — the HAPI public test server by default, or a
locally-run HAPI loaded with Synthea bundles. FHIR is the standard; Epic is one
implementation of it, so nothing here is Epic-specific and the same tools work
against an Epic sandbox by changing FHIR_BASE_URL.

Three constraints are enforced in this module rather than left to the caller:

Read-only. Only GET is implemented. The default base URL is a shared public
test server, and a tool that can POST to it is a tool that can corrupt other
people's test data. There is no write path to misuse.

Resource scoping. Every request passes through an allowlist. A tool asking for
a resource type outside FHIR_ALLOWED_RESOURCES is refused before any network
call, so scope is a property of the client, not a convention the tools follow.

Projection. FHIR resources are large and deeply nested; a single Patient can
run to kilobytes of JSON. Each resource type is mapped to a compact dict, so an
agent reads a summary rather than paying for the full envelope.

Identifier boundary: FHIR resource ids live in a DIFFERENT namespace from this
practice's internal patient_uuid. They are never equal and are never mapped to
each other. The scheduler's patient_uuid must never be sent to an external FHIR
server, and a FHIR id must never be treated as a scheduler patient.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://hapi.fhir.org/baseR4"
SUPPORTED_RESOURCES = ("Patient", "Condition", "MedicationRequest", "Observation")

FHIR_BASE_URL = os.environ.get("FHIR_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
FHIR_TIMEOUT = float(os.environ.get("FHIR_TIMEOUT", "30"))
FHIR_MAX_COUNT = int(os.environ.get("FHIR_MAX_COUNT", "50"))

_scope_env = os.environ.get("FHIR_ALLOWED_RESOURCES", "")
FHIR_ALLOWED_RESOURCES = (
    tuple(r.strip() for r in _scope_env.split(",") if r.strip()) or SUPPORTED_RESOURCES
)

JSON_HEADERS = {"Accept": "application/fhir+json"}


class FhirError(Exception):
    """A FHIR request failed in a way the agent should be told about verbatim."""


class ScopeError(FhirError):
    """The requested resource type is outside the configured scope."""


def check_scope(resource_type: str) -> None:
    if resource_type not in FHIR_ALLOWED_RESOURCES:
        raise ScopeError(
            f"{resource_type} is outside this server's configured FHIR scope "
            f"({', '.join(FHIR_ALLOWED_RESOURCES)})."
        )


def _describe_operation_outcome(payload: dict) -> str | None:
    """Turn a FHIR OperationOutcome into one line.

    FHIR servers signal errors with an OperationOutcome resource rather than a
    plain body, so an HTTP status alone loses the actual reason.
    """
    if payload.get("resourceType") != "OperationOutcome":
        return None
    parts = []
    for issue in payload.get("issue") or []:
        detail = (issue.get("details") or {}).get("text") or issue.get("diagnostics")
        code = issue.get("code", "")
        severity = issue.get("severity", "")
        parts.append(" ".join(x for x in (severity, code, detail) if x))
    return "; ".join(parts) or None


async def _get(
    path: str, params: dict[str, Any] | None = None, client: httpx.AsyncClient | None = None
) -> dict:
    """GET one FHIR path, translating transport and FHIR-level failures."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=FHIR_TIMEOUT)
    try:
        resp = await client.get(f"{FHIR_BASE_URL}{path}", params=params, headers=JSON_HEADERS)
    except httpx.TimeoutException as exc:
        raise FhirError(f"FHIR server timed out after {FHIR_TIMEOUT}s ({FHIR_BASE_URL}).") from exc
    except httpx.HTTPError as exc:
        raise FhirError(f"Could not reach the FHIR server at {FHIR_BASE_URL}: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

    try:
        payload = resp.json()
    except ValueError:
        raise FhirError(
            f"FHIR server returned HTTP {resp.status_code} with a non-JSON body."
        ) from None

    if resp.status_code >= 400:
        reason = _describe_operation_outcome(payload) or f"HTTP {resp.status_code}"
        raise FhirError(f"FHIR request failed: {reason}")

    # A 200 can still carry an OperationOutcome instead of the resource asked for.
    outcome = _describe_operation_outcome(payload)
    if outcome:
        raise FhirError(f"FHIR server returned an OperationOutcome: {outcome}")
    return payload


def _entries(bundle: dict) -> list[dict]:
    return [e["resource"] for e in (bundle.get("entry") or []) if "resource" in e]


def _codeable(concept: dict | None) -> str | None:
    """Best human-readable label from a CodeableConcept."""
    if not concept:
        return None
    if concept.get("text"):
        return concept["text"]
    for coding in concept.get("coding") or []:
        if coding.get("display"):
            return coding["display"]
        if coding.get("code"):
            return coding["code"]
    return None


def _human_name(resource: dict) -> str | None:
    for name in resource.get("name") or []:
        if name.get("text"):
            return name["text"]
        given = " ".join(name.get("given") or [])
        full = f"{given} {name.get('family', '')}".strip()
        if full:
            return full
    return None


# --- Projections: FHIR resource -> compact dict -----------------------------


def project_patient(r: dict) -> dict:
    return {
        "fhir_id": r.get("id"),
        "name": _human_name(r),
        "gender": r.get("gender"),
        "birth_date": r.get("birthDate"),
        "deceased": bool(r.get("deceasedBoolean") or r.get("deceasedDateTime")),
        "active": r.get("active"),
    }


def project_condition(r: dict) -> dict:
    return {
        "fhir_id": r.get("id"),
        "condition": _codeable(r.get("code")),
        "clinical_status": _codeable(r.get("clinicalStatus")),
        "verification_status": _codeable(r.get("verificationStatus")),
        "onset": r.get("onsetDateTime"),
        "recorded": r.get("recordedDate"),
    }


def project_medication_request(r: dict) -> dict:
    med = _codeable(r.get("medicationCodeableConcept"))
    if not med and r.get("medicationReference"):
        med = (r["medicationReference"] or {}).get("display")
    dosage = None
    for d in r.get("dosageInstruction") or []:
        if d.get("text"):
            dosage = d["text"]
            break
    return {
        "fhir_id": r.get("id"),
        "medication": med,
        "status": r.get("status"),
        "intent": r.get("intent"),
        "authored_on": r.get("authoredOn"),
        "dosage": dosage,
    }


def project_observation(r: dict) -> dict:
    value = None
    if r.get("valueQuantity"):
        q = r["valueQuantity"]
        value = " ".join(str(x) for x in (q.get("value"), q.get("unit")) if x is not None)
    elif r.get("valueCodeableConcept"):
        value = _codeable(r["valueCodeableConcept"])
    elif r.get("valueString"):
        value = r["valueString"]
    return {
        "fhir_id": r.get("id"),
        "observation": _codeable(r.get("code")),
        "value": value,
        "status": r.get("status"),
        "effective": r.get("effectiveDateTime"),
    }


PROJECTIONS = {
    "Patient": project_patient,
    "Condition": project_condition,
    "MedicationRequest": project_medication_request,
    "Observation": project_observation,
}


# --- Read operations --------------------------------------------------------


async def capability_summary(client: httpx.AsyncClient | None = None) -> dict:
    payload = await _get("/metadata", {"_summary": "true"}, client)
    software = payload.get("software") or {}
    return {
        "base_url": FHIR_BASE_URL,
        "fhir_version": payload.get("fhirVersion"),
        "software": software.get("name"),
        "software_version": software.get("version"),
        "allowed_resources": list(FHIR_ALLOWED_RESOURCES),
        "read_only": True,
    }


async def search_patients(
    name: str | None = None,
    family: str | None = None,
    identifier: str | None = None,
    count: int = 10,
    client: httpx.AsyncClient | None = None,
) -> dict:
    check_scope("Patient")
    params: dict[str, Any] = {"_count": min(count, FHIR_MAX_COUNT)}
    if name:
        params["name"] = name
    if family:
        params["family"] = family
    if identifier:
        params["identifier"] = identifier
    bundle = await _get("/Patient", params, client)
    return {
        "resource_type": "Patient",
        "count": len(_entries(bundle)),
        "patients": [project_patient(r) for r in _entries(bundle)],
    }


async def get_patient(fhir_id: str, client: httpx.AsyncClient | None = None) -> dict:
    check_scope("Patient")
    payload = await _get(f"/Patient/{fhir_id}", None, client)
    return project_patient(payload)


async def get_resources_for_patient(
    resource_type: str,
    fhir_patient_id: str,
    count: int = 25,
    client: httpx.AsyncClient | None = None,
    extra: dict[str, Any] | None = None,
) -> dict:
    """Search one clinical resource type scoped to a single patient.

    patient= is a server-side filter, so the bundle never contains another
    patient's resources to be filtered out client-side.
    """
    check_scope(resource_type)
    params: dict[str, Any] = {"patient": fhir_patient_id, "_count": min(count, FHIR_MAX_COUNT)}
    params.update(extra or {})
    bundle = await _get(f"/{resource_type}", params, client)
    project = PROJECTIONS[resource_type]
    records = [project(r) for r in _entries(bundle)]
    return {
        "resource_type": resource_type,
        "fhir_patient_id": fhir_patient_id,
        "count": len(records),
        "records": records,
    }
