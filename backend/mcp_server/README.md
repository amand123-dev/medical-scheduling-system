# MCP Server — SmallPractice Scheduler

Exposes the scheduler to MCP clients (Claude Desktop, Claude Code) as a set of tools.

## Design

The server holds **no business logic**. Every tool is a thin adapter over the FastAPI
HTTP API:

```
MCP client → mcp_server/server.py → FastAPI → matcher / scorer / retrieval → Postgres
```

This is deliberate. Routing through the API means an agent is just another API consumer:

- It authenticates as a **staff user** and is bound by that user's role. `get_patient_context`
  returns 403 for a `front_desk` token, exactly as the web UI does.
- Patient-scoped reads write to `identity_access_log`, so agent access is as auditable as
  human access — same table, same code path.
- Operational tools return **UUIDs only**, never names. There is no tool that resolves a
  UUID to a person; that stays in the audited reverse-lookup in the web UI.

A direct-to-database MCP server would have bypassed all three. `tests/test_mcp_server.py`
enforces this by failing if `server.py` ever imports SQLAlchemy or the retrieval layer.

## Tools

Two groups, deliberately kept in separate namespaces.

### Scheduler tools — this practice's own API

| Tool | PHI | Role required |
|---|---|---|
| `search_protocols` | none | any staff |
| `get_patient_context` | patient documents — **audited** | admin, provider |
| `find_next_available` | none | any staff |
| `list_providers` | none | any staff |
| `list_visit_types` | none | any staff |
| `list_waitlist` | UUIDs only | any staff |
| `get_no_show_risk` | UUID + score | any staff |
| `get_dashboard_metrics` | aggregate only | any staff |

### FHIR R4 tools — an external clinical server

`fhir_server_info`, `fhir_search_patients`, `fhir_get_patient`,
`fhir_get_conditions`, `fhir_get_medications`, `fhir_get_observations`.

These read a standard FHIR R4 endpoint — the HAPI public test server by
default. FHIR is the standard and Epic is one implementation of it, so nothing
here is Epic-specific: pointing `FHIR_BASE_URL` at an Epic sandbox, a local
HAPI loaded with Synthea bundles, or any other R4 server works unchanged.

Three properties are enforced in `fhir.py` rather than left to each tool:

- **Read-only.** Only GET is implemented. The default base URL is a shared
  public test server that anyone can write to; a tool that can POST to it is a
  tool that can corrupt other people's test data. There is no write path.
- **Resource-level scoping.** Every request passes an allowlist
  (`FHIR_ALLOWED_RESOURCES`) *before* the network call, so scope is a property
  of the client rather than a convention the tools follow.
- **Projection.** Each resource type is mapped to a compact dict. A raw FHIR
  Patient runs to kilobytes; an agent should read a summary, not an envelope.

Errors are surfaced from the FHIR `OperationOutcome` resource, not inferred
from the HTTP status — a bare 404 loses the reason, and FHIR servers return a
200 carrying an OperationOutcome often enough that status alone is unreliable.

**Identifier boundary:** FHIR resource ids are a *different namespace* from
this practice's `patient_uuid`. They are never equal and are never mapped to
each other. The scheduler's UUIDs are never sent to an external FHIR server.

**Why these are not merged into `get_patient_context`:** that tool is governed
by the scheduler's role checks and writes `identity_access_log`. None of that
applies to a third-party API. Collapsing the two would imply audit coverage
that does not exist.

### FHIR configuration

| Variable | Default |
|---|---|
| `FHIR_BASE_URL` | `https://hapi.fhir.org/baseR4` |
| `FHIR_ALLOWED_RESOURCES` | `Patient,Condition,MedicationRequest,Observation` |
| `FHIR_MAX_COUNT` | `50` |
| `FHIR_TIMEOUT` | `30` |

The public HAPI server holds synthetic records uploaded by many people. Its
contents change without notice, so tests never assert against specific patient
ids. Live checks are opt-in: `pytest -m live`.

## Install

The MCP SDK requires a newer Starlette than the pinned FastAPI accepts, so this runs in
its own virtualenv:

```bash
python -m venv .venv-mcp
.venv-mcp/bin/pip install -r mcp_server/requirements.txt
```

## Run

Start the API first, then get a staff token:

```bash
uvicorn app.main:app --reload
curl -s -X POST localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"..."}' | jq -r .access_token
```

```bash
export SCHEDULER_API_URL=http://localhost:8000
export SCHEDULER_API_TOKEN=<token>
.venv-mcp/bin/python -m mcp_server.server
```

## Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "smallpractice-scheduler": {
      "command": "/absolute/path/to/backend/.venv-mcp/bin/python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/absolute/path/to/backend",
      "env": {
        "SCHEDULER_API_URL": "http://localhost:8000",
        "SCHEDULER_API_TOKEN": "<staff token>"
      }
    }
  }
}
```

## Notes

- Tokens expire. A 401 means re-issue the token; the server does not refresh.
- Synthetic data only. Do not point this at anything holding real patient
  information, and never send this practice's data to an external FHIR server.
- This is a portfolio demonstration of MCP tool design under a data-minimization
  constraint — it is HIPAA-aware, not HIPAA compliant, and is not a cleared medical device.
