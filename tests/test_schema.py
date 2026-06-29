"""Tests for the JSON Schema export module."""

from __future__ import annotations

import json
from pathlib import Path

from telemachy.models import WorkflowSpec
from telemachy.schema import get_workflow_schema, write_workflow_schema


class TestGetWorkflowSchema:
    def test_returns_dict(self) -> None:
        schema = get_workflow_schema()
        assert isinstance(schema, dict)

    def test_has_properties_section(self) -> None:
        schema = get_workflow_schema()
        assert "properties" in schema

    def test_contains_all_top_level_fields(self) -> None:
        schema = get_workflow_schema()
        for field in ("apiVersion", "metadata", "agents", "teams", "teardown"):
            assert field in schema["properties"], f"missing field {field!r}"

    def test_is_json_serialisable(self) -> None:
        schema = get_workflow_schema()
        # Must not raise — schema is used for editor validation.
        json.dumps(schema)

    def test_references_nested_specs_via_defs(self) -> None:
        schema = get_workflow_schema()
        assert "$defs" in schema
        # AgentSpec, TaskSpec, TeamSpec all appear as $def keys.
        for nested in ("AgentSpec", "TaskSpec", "TeamSpec"):
            assert nested in schema["$defs"], f"missing $def {nested!r}"

    def test_matches_model_json_schema(self) -> None:
        # The function is a thin wrapper; verify equivalence so future drift
        # in WorkflowSpec is auto-reflected.
        assert get_workflow_schema() == WorkflowSpec.model_json_schema()


class TestWriteWorkflowSchema:
    def test_writes_file(self, tmp_path: Path) -> None:
        target = tmp_path / "schema.json"
        write_workflow_schema(target)
        assert target.exists()

    def test_content_is_indented_json(self, tmp_path: Path) -> None:
        target = tmp_path / "schema.json"
        write_workflow_schema(target)
        text = target.read_text()
        # Pretty-printed with indent=2.
        assert "\n  " in text

    def test_content_round_trips_to_schema(self, tmp_path: Path) -> None:
        target = tmp_path / "schema.json"
        write_workflow_schema(target)
        loaded = json.loads(target.read_text())
        assert loaded == get_workflow_schema()

    def test_file_ends_with_newline(self, tmp_path: Path) -> None:
        target = tmp_path / "schema.json"
        write_workflow_schema(target)
        assert target.read_text().endswith("\n")

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "schema.json"
        target.write_text("stale content")
        write_workflow_schema(target)
        assert "stale content" not in target.read_text()
        assert json.loads(target.read_text()) == get_workflow_schema()
