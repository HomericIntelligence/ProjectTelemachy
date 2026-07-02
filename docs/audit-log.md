# Audit Log Reference

## Overview

ProjectTelemachy records all workflow execution events to a structured JSONL audit log when configured with
`AUDIT_LOG_PATH`. The audit log serves as a tamper-evident record of:

- **Who** ran the workflow (hostname, user account)
- **When** each event occurred (UTC ISO 8601 timestamp)
- **What** happened (event type, workflow ID, resource IDs)
- **Outcome** of tasks, teams, and the workflow itself

The audit log uses SHA-256 hashing to form a continuity-aware hash chain, protecting against tampering and providing
evidence of execution integrity across process restarts.

## Configuration

Set these environment variables to enable audit logging:

```bash
# Path to JSONL audit log file. When unset, audit emission is a no-op (NullSink).
AUDIT_LOG_PATH=/var/log/telemachy/audit.jsonl

# SHA-256 hash chain for tamper-evident audit log. Resumes from existing file on restart.
# Defaults to true; set to false only for tooling/tests that do not require tamper-evidence.
AUDIT_HASH_CHAIN=true
```

See `.env.example` for commented-out defaults.

## Event Types

Each audit record is a JSON object with these mandatory fields:

```json
{
  "timestamp": "2026-06-04T15:30:45.123456",
  "event_type": "workflow.started",
  "workflow_id": "a1b2c3d4",
  "actor": {
    "host_id": "hermes",
    "user": "alice"
  },
  "payload": { /* event-specific fields */ },
  "prev_hash": "0000...",
  "hash": "a1b2c3..."
}
```

### Workflow Events

- **`workflow.started`** — Workflow execution begins

  ```json
  "payload": {
    "spec_name": "deploy-fleet",
    "agents": ["agent-a", "agent-b"],
    "teams": ["team-1"],
    "teardown": "on_completion"
  }
  ```

- **`workflow.completed`** — Workflow finished successfully

  ```json
  "payload": {
    "spec_name": "deploy-fleet",
    "duration_seconds": 42.5
  }
  ```

- **`workflow.cancelled`** — Workflow was cancelled via stop event

  ```json
  "payload": {
    "spec_name": "deploy-fleet"
  }
  ```

- **`workflow.failed`** — Workflow encountered an error

  ```json
  "payload": {
    "spec_name": "deploy-fleet",
    "error": "One or more tasks failed during workflow execution"
  }
  ```

### Agent Events

- **`agent.created`** — Agent provisioned

  ```json
  "payload": {
    "agent_name": "worker-1",
    "agent_id": "maestro-xyz",
    "runtime": "local",
    "program": "claude-code"
  }
  ```

- **`agent.deleted`** — Agent deleted during teardown

  ```json
  "payload": {
    "agent_name": "worker-1",
    "agent_id": "maestro-xyz"
  }
  ```

### Team Events

- **`team.created`** — Team provisioned

  ```json
  "payload": {
    "team_name": "backend-team",
    "team_id": "team-abc123",
    "members": ["worker-1", "worker-2"]
  }
  ```

- **`team.deleted`** — Team deleted during teardown

  ```json
  "payload": {
    "team_name": "backend-team",
    "team_id": "team-abc123"
  }
  ```

### Task Events

- **`task.submitted`** — Task submitted to Agamemnon

  ```json
  "payload": {
    "team_id": "team-abc123",
    "task_subject": "Deploy services",
    "task_id": "task-1",
    "assign_to": "worker-1",
    "blocked_by": ["setup-task"]
  }
  ```

- **`task.completed`** — Task finished successfully

  ```json
  "payload": {
    "workflow_id": "a1b2c3d4",
    "team": "backend-team",
    "task_subject": "Deploy services"
  }
  ```

- **`task.failed`** — Task encountered an error

  ```json
  "payload": {
    "workflow_id": "a1b2c3d4",
    "team": "backend-team",
    "task_subject": "Deploy services"
  }
  ```

## Hash Chain Verification

If `AUDIT_HASH_CHAIN=true` (the default), each record includes a SHA-256 hash of all its fields, with a `prev_hash`
field linking to the previous record's hash. This forms an append-only chain that detects any tampering.

### Verifying the chain

```python
import json
from pathlib import Path

audit_file = Path("/var/log/telemachy/audit.jsonl")
records = [json.loads(line) for line in audit_file.read_text().splitlines()]

# The first record should reference the genesis hash
assert records[0]["prev_hash"] == "0" * 64

# Each subsequent record should link to the previous one
for i in range(1, len(records)):
    assert records[i]["prev_hash"] == records[i-1]["hash"], \
        f"Chain broken at record {i}"

print(f"✓ Audit chain verified: {len(records)} records, no tampering detected")
```

### Chain Continuity Across Restarts

On process restart, the audit sink reads the last JSON record from the existing log and seeds the hash chain from its
`hash` field. This ensures that:

1. The chain does not silently reset to the genesis hash
2. Any corruption in the existing log (missing or malformed `hash` field) is detected as `AuditChainError` at startup
3. Each process continues the same chain rather than creating disconnected chains

## Actor Field Portability

The `actor` object always includes:

- `host_id` — Configured via `HOST_ID` env var (default: `"hermes"`)
- `user` — Resolved from `USER` env var (POSIX), then `USERNAME` (Windows), then `"unknown"`

On CI systems or sandboxes that strip both env vars, `actor.user` will be `"unknown"`. A single warning log is emitted
when this occurs.

## Log Retention and Archival

The JSONL format streams cleanly into external logging systems:

```bash
# Tail the audit log into Loki, Splunk, or similar
tail -f /var/log/telemachy/audit.jsonl | curl -X POST -d @- http://loki:3100/...
```

Retention policies are typically set per downstream system. Archive the JSONL file after retention windows expire if
long-term auditability is required.

## Example: Reading the Audit Log

```python
import json
from pathlib import Path
from datetime import datetime

audit_file = Path("/var/log/telemachy/audit.jsonl")
records = [json.loads(line) for line in audit_file.read_text().splitlines()]

# Print summary of all workflow events
for rec in records:
    if rec["event_type"].startswith("workflow."):
        ts = datetime.fromisoformat(rec["timestamp"])
        print(f"{ts.isoformat()}: {rec['event_type']} "
              f"(wf={rec['workflow_id']}, actor={rec['actor']['user']})")

# Count tasks by status
task_events = [r for r in records if r["event_type"].startswith("task.")]
completed = sum(1 for r in task_events if r["event_type"] == "task.completed")
failed = sum(1 for r in task_events if r["event_type"] == "task.failed")
print(f"\nTasks: {completed} completed, {failed} failed")
```
