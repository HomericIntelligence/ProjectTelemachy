"""JSON Schema export for workflow YAML validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from telemachy.models import WorkflowSpec


def get_workflow_schema() -> dict[str, Any]:
    """Return the JSON Schema for WorkflowSpec."""
    return WorkflowSpec.model_json_schema()


def write_workflow_schema(path: Path) -> None:
    """Write the workflow JSON Schema to a file."""
    schema = get_workflow_schema()
    path.write_text(json.dumps(schema, indent=2) + "\n")
