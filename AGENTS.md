# AGENTS.md - Multi-Agent Coordination Protocols

ProjectTelemachy is a declarative workflow engine for coordinating multiple AI agents via ProjectAgamemnon. This document defines how agents collaborate, communicate, and hand off work.

## Agent Roles

### Workflow Executor
- **Purpose**: Orchestrates multi-agent workflow execution
- **Responsibilities**:
  - Parse workflow specifications
  - Provision agent teams via Agamemnon
  - Monitor task completion
  - Handle failures and retries

### Agent Teams
Teams are created per workflow with specific agent compositions:
- **Researcher Agents**: Information gathering and analysis
- **Coder Agents**: Implementation and code review
- **Validator Agents**: Quality assurance and testing

## Coordination Patterns

### Sequential Execution
Tasks run in dependency order. Task B waits for Task A to complete:
```yaml
tasks:
  - subject: "Analyze requirements"
    assign_to: researcher
  - subject: "Implement solution"
    assign_to: coder
    blocked_by: ["Analyze requirements"]
```

### Parallel Execution
Multiple agents work independently on different tasks:
```yaml
tasks:
  - subject: "Frontend implementation"
    assign_to: frontend_agent
  - subject: "Backend implementation"
    assign_to: backend_agent
```

### Handoff Protocol
When one agent completes work for another:
1. Task completion is reported to Agamemnon
2. Dependent tasks are automatically unblocked
3. Next agent receives task context via task description

## Communication

### NATS Messaging
- All inter-agent communication flows through NATS JetStream
- Topics follow pattern: `hi.agents.{workflow_id}.{task_id}`
- Messages include: task context, completion status, handoff data

### Task Context
Each task carries:
- Workflow ID
- Parent task results (if any)
- Agent-specific instructions
- Output expectations

## Error Handling

### Agent Failure
- Failed tasks are reported to Agamemnon
- Dependent tasks are skipped (not blocked forever)
- Workflow continues with available agents

### Timeout
- Default timeout: 2 hours per workflow
- Configurable via `DEFAULT_WORKFLOW_TIMEOUT`
- Monitor polls every 5 seconds for status updates

## Best Practices

1. **Define clear task boundaries**: Each task should have a single responsibility
2. **Use descriptive subjects**: Task names should indicate purpose
3. **Specify dependencies explicitly**: Use `blocked_by` for ordering
4. **Handle failures gracefully**: Design workflows to continue on partial failure

## Configuration

See `.env.example` for all configurable options:
- `AGAMEMNON_URL`: Agamemnon API endpoint
- `NATS_URL`: NATS message broker
- `HOST_ID`: Identifier for this workflow runner
- `MONITOR_TIMEOUT_SECONDS`: Max time waiting for tasks
- `DEFAULT_WORKFLOW_TIMEOUT`: Default workflow execution limit
