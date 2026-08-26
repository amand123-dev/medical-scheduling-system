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
- Synthetic data only. Do not point this at anything holding real patient information.
- This is a portfolio demonstration of MCP tool design under a data-minimization
  constraint — it is HIPAA-aware, not HIPAA compliant, and is not a cleared medical device.
