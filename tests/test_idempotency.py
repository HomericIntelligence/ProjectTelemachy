from telemachy.idempotency import is_telemachy_key, make_key


def test_make_key_is_deterministic() -> None:
    assert make_key("wf-a", "worker") == make_key("wf-a", "worker")


def test_make_key_workflow_scoped() -> None:
    assert make_key("wf-a", "worker") != make_key("wf-b", "worker")


def test_make_key_resource_scoped() -> None:
    assert make_key("wf-a", "agent-a") != make_key("wf-a", "agent-b")


def test_make_key_format_and_recognition() -> None:
    k = make_key("wf-a", "worker")
    assert k.startswith("tlm-")
    assert k.endswith("-worker")
    assert is_telemachy_key(k)
    assert not is_telemachy_key("user-created-agent")


def test_make_key_sanitises_unsafe_chars() -> None:
    k = make_key("wf-a", "weird name/with spaces!")
    assert "/" not in k and " " not in k and "!" not in k
