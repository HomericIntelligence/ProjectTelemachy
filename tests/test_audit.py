"""Contract tests for AuditSink — written before implementation (TDD)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from telemachy.audit import AuditChainError, AuditSink, NullSink


def _new_sink(tmp_path: Path, *, chain: bool = True) -> AuditSink:
    return AuditSink(path=tmp_path / "audit.jsonl", host_id="test-host", hash_chain=chain)


def test_null_sink_is_noop(tmp_path: Path) -> None:
    sink = NullSink()
    sink.emit("workflow.started", workflow_id="x")
    sink.close()
    assert not (tmp_path / "audit.jsonl").exists()


def test_emit_writes_one_jsonl_line(tmp_path: Path) -> None:
    sink = _new_sink(tmp_path, chain=False)
    sink.emit("workflow.started", workflow_id="wf-1", spec_name="demo")
    sink.close()
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event_type"] == "workflow.started"
    assert rec["workflow_id"] == "wf-1"
    assert rec["payload"] == {"spec_name": "demo"}
    assert rec["actor"] == {"host_id": "test-host", "user": rec["actor"]["user"]}
    assert "timestamp" in rec


def test_concurrent_emit_no_interleaving(tmp_path: Path) -> None:
    sink = _new_sink(tmp_path, chain=False)

    def fire(i: int) -> None:
        sink.emit("e", workflow_id=None, i=i)

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sink.close()
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 100
    for line in lines:
        json.loads(line)  # all intact


def test_hash_chain_within_process(tmp_path: Path) -> None:
    sink = _new_sink(tmp_path)
    sink.emit("a", workflow_id="w")
    sink.emit("b", workflow_id="w")
    sink.close()
    lines = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert lines[0]["prev_hash"] == "0" * 64
    assert lines[1]["prev_hash"] == lines[0]["hash"]


def test_hash_chain_resumes_across_sinks(tmp_path: Path) -> None:
    """Restart safety: a second sink on the same file resumes, not zero-restarts."""
    s1 = _new_sink(tmp_path)
    s1.emit("a", workflow_id="w")
    s1.close()
    s2 = _new_sink(tmp_path)
    s2.emit("b", workflow_id="w")
    s2.close()
    lines = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert lines[1]["prev_hash"] == lines[0]["hash"]
    assert lines[1]["prev_hash"] != "0" * 64


def test_corrupt_tail_raises_on_resume(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text("{not json\n")
    with pytest.raises(AuditChainError):
        AuditSink(path=path, host_id="h", hash_chain=True)


def test_write_error_swallowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sink = _new_sink(tmp_path, chain=False)

    def boom(*a, **kw):  # type: ignore
        raise OSError("disk full")

    monkeypatch.setattr(sink, "_open", boom)
    sink.emit("a", workflow_id="x")  # must not raise
