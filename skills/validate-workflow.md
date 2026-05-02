# Workflow Validation Skill

This skill provides guidance for validating Telemachy workflow YAML files before execution.

## Quick Validation

### Schema Validation
```bash
# Generate and validate against JSON schema
just schema > workflow.schema.json
just validate your-workflow.yaml
```

### Dry Run
```bash
# See what would be created without executing
just plan your-workflow.yaml
```

## Common Issues

### Missing Dependencies
If a task references an agent that doesn't exist:
```yaml
tasks:
  - subject: "Do work"
    assign_to: nonexistent_agent  # ERROR: Agent not found
```

**Fix**: Ensure all `assign_to` values match defined agents in the workflow.

### Circular Dependencies
```yaml
tasks:
  - subject: "Task A"
    blocked_by: ["Task B"]
  - subject: "Task B"
    blocked_by: ["Task A"]  # ERROR: Circular dependency
```

**Fix**: Remove circular dependencies; use sequential execution instead.

### Invalid YAML
Always validate YAML syntax:
```bash
python -c "import yaml; yaml.safe_load(open('workflow.yaml'))"
```

## Best Practices

1. **Use descriptive task subjects**: Clear names help with debugging
2. **Group related tasks in teams**: Teams share context and resources
3. **Set appropriate timeouts**: Long-running tasks need more time
4. **Test locally first**: Use `just plan` before `just run`

## Environment Setup

Ensure your `.env` is configured:
```bash
AGAMEMNON_URL=http://localhost:8080
AGAMEMNON_API_KEY=your-key
NATS_URL=nats://localhost:4222
```

## Troubleshooting

### "Connection refused" to Agamemnon
- Verify Agamemnon is running: `curl http://localhost:8080/health`
- Check `AGAMEMNON_URL` in `.env`

### "Task failed" errors
- Check Agamemnon logs for agent errors
- Verify agent programs are accessible
- Ensure NATS broker is running
