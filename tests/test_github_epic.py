"""Tests for telemachy.github_epic (register-epic, Odysseus ADR-013 §6)."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from telemachy.github_epic import (
    envelope,
    epic_key,
    ordered_tasks,
    register_epic,
    slugify,
)
from tests.conftest import make_agent_dict, make_team_dict, make_workflow_spec


def _dep_spec() -> Any:
    """Workflow with two agents and one dependency edge."""
    return make_workflow_spec(
        name="dep-workflow",
        description="Workflow with task dependency",
        agents=[make_agent_dict("agent-a"), make_agent_dict("agent-b")],
        teams=[
            make_team_dict(
                name="dep-team",
                agents=["agent-a", "agent-b"],
                tasks=[
                    {
                        "subject": "task-two",
                        "description": "second",
                        "assign_to": "agent-b",
                        "blocked_by": ["task-one"],
                    },
                    {
                        "subject": "task-one",
                        "description": "first",
                        "assign_to": "agent-a",
                        "blocked_by": [],
                    },
                ],
            )
        ],
    )


class FakeGh:
    """Records gh invocations and mints sequential issue numbers."""

    def __init__(self, start: int = 100) -> None:
        self.calls: list[list[str]] = []
        self._next = start

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if args[:2] == ["repo", "view"]:
            return json.dumps({"nameWithOwner": "Homeric/Repo"})
        if args[:2] == ["issue", "create"]:
            self._next += 1
            return f"https://github.com/Homeric/Repo/issues/{self._next}\n"
        return ""

    def created_issues(self) -> list[list[str]]:
        return [c for c in self.calls if c[:2] == ["issue", "create"]]


class TestHelpers:
    """Tests for the pure helpers."""

    def test_slugify_repo(self) -> None:
        assert slugify("HomericIntelligence/Odysseus") == "homericintelligence-odysseus"

    def test_epic_key(self) -> None:
        assert epic_key("Homeric/Repo", 12) == "homeric-repo-12"

    def test_envelope(self) -> None:
        body = envelope(workflow="w")
        assert body["schema"] == "hi/v1"
        assert body["workflow"] == "w"
        assert body["msg_id"] and body["ts"]

    def test_ordered_tasks_deps_first(self) -> None:
        ordered = ordered_tasks(_dep_spec())
        assert [t.subject for t in ordered] == ["task-one", "task-two"]


class TestRegisterEpic:
    """Tests for register_epic()."""

    def test_creates_children_then_epic_and_publishes(self) -> None:
        gh = FakeGh()
        published: list[tuple[str, dict[str, Any], str]] = []

        result = register_epic(
            _dep_spec(),
            repo="Homeric/Repo",
            nats_url="nats://x:4222",
            gh=gh,
            publish=lambda s, p, u: published.append((s, p, u)),
        )

        # Children minted in dependency order, epic last.
        creates = gh.created_issues()
        assert len(creates) == 3
        titles = [c[c.index("--title") + 1] for c in creates]
        assert titles == ["task-one", "task-two", "[epic] dep-workflow"]
        assert result["children"] == {"task-one": 101, "task-two": 102}
        assert result["epic"] == 103
        assert result["key"] == "homeric-repo-103"

        # Child labels + dependency lines.
        child_two = creates[1]
        assert child_two[child_two.index("--label") + 1] == "state:needs-plan"
        assert "Depends on #101" in child_two[child_two.index("--body") + 1]

        # Epic body carries the parseable task list.
        epic_body = creates[2][creates[2].index("--body") + 1]
        assert "- [ ] #101" in epic_body
        assert "- [ ] #102 (depends on: #101)" in epic_body
        assert creates[2][creates[2].index("--label") + 1] == "agamemnon-epic"

        # Trigger published with hi/v1 envelope.
        subject, payload, url = published[0]
        assert subject == "hi.pipeline.epic.homeric-repo-103.registered"
        assert payload["schema"] == "hi/v1"
        assert payload["epic"] == {"repo": "Homeric/Repo", "issue": 103, "key": "homeric-repo-103"}
        assert payload["children"] == [101, 102]
        assert url == "nats://x:4222"

    def test_repo_defaults_to_current(self) -> None:
        gh = FakeGh()
        result = register_epic(_dep_spec(), gh=gh, publish=lambda s, p, u: None)
        assert result["repo"] == "Homeric/Repo"
        assert gh.calls[0][:2] == ["repo", "view"]

    def test_dry_run_creates_nothing(self) -> None:
        gh = FakeGh()
        published: list[Any] = []

        result = register_epic(
            _dep_spec(),
            repo="Homeric/Repo",
            dry_run=True,
            gh=gh,
            publish=lambda s, p, u: published.append(s),
        )

        assert result["dry_run"] is True
        assert result["children"] == {"task-one": None, "task-two": None}
        assert gh.created_issues() == []
        assert published == []

    def test_unparseable_issue_url_raises(self) -> None:
        def bad_gh(args: list[str]) -> str:
            if args[:2] == ["issue", "create"]:
                return "no url here"
            return ""

        with pytest.raises(RuntimeError, match="could not parse issue number"):
            register_epic(
                _dep_spec(), repo="o/r", gh=bad_gh, publish=lambda s, p, u: None
            )


class TestCliCommand:
    """Tests for the register-epic CLI wiring."""

    def test_json_contract_on_stdout(self, workflow_file_factory: Any, monkeypatch: Any) -> None:
        from unittest.mock import patch

        from typer.testing import CliRunner

        from telemachy.cli import app

        runner = CliRunner()
        path = workflow_file_factory()
        canned = {"epic": 7, "key": "o-r-7", "repo": "o/r", "children": {"t": 6}, "subject": "s"}
        with patch("telemachy.github_epic.register_epic", return_value=canned):
            result = runner.invoke(app, ["register-epic", str(path), "--repo", "o/r"])

        assert result.exit_code == 0, result.output
        last_line = [ln for ln in result.output.strip().splitlines() if ln.startswith("{")][-1]
        assert json.loads(last_line) == canned

    def test_failure_exits_nonzero(self, workflow_file_factory: Any) -> None:
        from unittest.mock import patch

        from typer.testing import CliRunner

        from telemachy.cli import app

        runner = CliRunner()
        path = workflow_file_factory()
        with patch("telemachy.github_epic.register_epic", side_effect=RuntimeError("boom")):
            result = runner.invoke(app, ["register-epic", str(path)])

        assert result.exit_code == 1
        assert not re.search(r"^\{", result.output, re.MULTILINE)
