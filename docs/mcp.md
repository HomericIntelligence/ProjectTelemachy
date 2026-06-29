# MCP (Model Context Protocol) Server

The ProjectTelemachy MCP server (`telemachy-mcp`) provides read-only access to live Agamemnon state during development. It allows AI agents working in this repository to query agents and tasks without requiring direct HTTP access to the Agamemnon API.

## What It Exposes

Two tools, both read-only:

| Tool | Description | Arguments |
| --- | --- | --- |
| `agamemnon_list_agents` | List all agents currently known to Agamemnon | None |
| `agamemnon_list_team_tasks` | List all tasks for a given Agamemnon team | `team_id` (string, required) |

## Enabling the Server

The `.mcp.json` at the repository root is auto-discovered by Claude Code. It automatically spawns the `telemachy-mcp` console script when Claude Code opens the project.

No configuration is required beyond the environment variables listed below.

## Environment Variables

The MCP server reuses the following environment variables from ProjectTelemachy's standard configuration:

- `AGAMEMNON_URL` (default: `http://localhost:8080`) — Agamemnon base URL
- `AGAMEMNON_API_KEY` (optional) — Agamemnon API key (if auth is enabled)
- `REQUIRE_TLS` (default: `false`) — Enforce TLS for Agamemnon connections

No new environment variables are introduced.

## Local Testing

### Smoke Test (Without Live Agamemnon)

You can test the server against a mock Agamemnon using a simple HTTP server:

```bash
# Set up fixture data
mkdir -p /tmp/fakeagm/v1
echo '{"agents":[]}' > /tmp/fakeagm/v1/agents

# Start the fixture server in the background
(cd /tmp/fakeagm && python -m http.server 8080 &)
sleep 1

# Run the MCP server and send a tools/list request
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
    REQUIRE_TLS=false AGAMEMNON_URL=http://localhost:8080 just mcp
```

Expected output: JSON-RPC response containing both tool names (`agamemnon_list_agents`, `agamemnon_list_team_tasks`).

### Interactive Testing

```bash
# Run the MCP server
just mcp

# In another terminal, send JSON-RPC messages over stdin:
# - Initialization: {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test"}}}
# - List tools: {"jsonrpc":"2.0","id":2,"method":"tools/list"}
# - Call tool: {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"agamemnon_list_agents","arguments":{}}}
```

## Non-Goals

The following are explicitly deferred or out-of-scope:

- **Write endpoints** — No endpoints for creating, starting, or deleting agents; no task assignment. The server is read-only.
- **NATS subscription** — Live event monitoring via NATS is planned under issue #92 and not yet wired. No NATS state is exposed.

## Implementation

See [issue #173](https://github.com/ProjectTelemachy/telemachy/issues/173) for full details. The implementation uses a plan-owned `Dispatcher` seam in `src/telemachy/mcp_server.py` to keep tests isolated from the MCP SDK's private internals.
