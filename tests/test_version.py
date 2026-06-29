"""Verify package __version__ stays in sync with pyproject.toml — see #177."""

from __future__ import annotations

import tomllib
from pathlib import Path

import telemachy


def test_package_version_matches_pyproject() -> None:
    """telemachy.__version__ MUST equal pyproject.toml [project].version."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    assert telemachy.__version__ == data["project"]["version"], (
        f"telemachy.__version__ ({telemachy.__version__}) "
        f"!= pyproject.toml version ({data['project']['version']}); "
        "bump both together."
    )


def test_package_exposes_dunder_version() -> None:
    """Package MUST expose __version__ — the deps/version-sync CI gate depends on it (#177)."""
    assert hasattr(telemachy, "__version__"), (
        "telemachy.__version__ must be defined in src/telemachy/__init__.py; "
        "the deps/version-sync CI check requires it."
    )
    assert isinstance(telemachy.__version__, str)
    assert telemachy.__version__  # non-empty
