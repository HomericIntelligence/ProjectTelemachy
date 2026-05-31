"""Tests for configuration settings."""

import logging

import pytest

from telemachy.config import Settings


def test_require_tls_default_is_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that REQUIRE_TLS defaults to True."""
    monkeypatch.delenv("REQUIRE_TLS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.require_tls is True


def test_require_tls_false_emits_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify that setting REQUIRE_TLS=false emits a WARNING."""
    monkeypatch.setenv("REQUIRE_TLS", "false")
    with caplog.at_level(logging.WARNING, logger="telemachy.config"):
        Settings(_env_file=None)
    assert any("cleartext" in record.message for record in caplog.records)


def test_require_tls_true_emits_no_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify that default REQUIRE_TLS=true emits no warning."""
    monkeypatch.delenv("REQUIRE_TLS", raising=False)
    with caplog.at_level(logging.WARNING, logger="telemachy.config"):
        Settings(_env_file=None)
    assert not any("cleartext" in record.message for record in caplog.records)


def test_client_kwargs_propagates_require_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that client_kwargs() propagates require_tls correctly."""
    # Test default (True)
    monkeypatch.delenv("REQUIRE_TLS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.client_kwargs()["require_tls"] is True

    # Test override (False)
    monkeypatch.setenv("REQUIRE_TLS", "false")
    settings = Settings(_env_file=None)
    assert settings.client_kwargs()["require_tls"] is False
