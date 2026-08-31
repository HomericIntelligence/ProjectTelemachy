"""Fail-closed contract for the required dependency-audit CI path."""

from __future__ import annotations

import os
import stat
import subprocess
import textwrap
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_RUNNER = REPO_ROOT / "scripts" / "run_ci_local.sh"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(textwrap.dedent(source))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_dependency_scan(tmp_path: Path, audit_status: int) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    fake_pixi = fake_bin / "pixi"
    _write_executable(
        fake_pixi,
        f"""\
        #!/bin/sh
        if [ "$1" = "install" ]; then
            exit 0
        fi
        if [ "$1" = "run" ] && [ "$2" = "pip-audit" ]; then
            exit {audit_status}
        fi
        echo "unexpected pixi invocation: $*" >&2
        exit 64
        """,
    )

    fake_engine = fake_bin / "container-engine"
    _write_executable(
        fake_engine,
        """\
        #!/bin/bash
        set -euo pipefail
        if [[ "$1 $2" == "image inspect" ]]; then
            exit 0
        fi
        if [[ "$1" == "run" ]]; then
            command="${!#}"
            # The real runner may prefix a container-only stale-environment
            # guard. Never execute that host-destructive guard in this fixture;
            # retain only the exact command that runs inside the container.
            command="pixi install --locked --quiet${command#*pixi install --locked --quiet}"
            PATH="${FAKE_BIN}:$PATH" bash -c "$command"
            exit $?
        fi
        echo "unexpected container-engine invocation: $*" >&2
        exit 64
        """,
    )

    env = {
        **os.environ,
        "CONTAINER_ENGINE": str(fake_engine),
        "FAKE_BIN": str(fake_bin),
        "HOME": str(tmp_path / "home"),
    }
    return subprocess.run(
        ["bash", str(CI_RUNNER), "security-dependency-scan"],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("audit_status", [1, 127])
def test_dependency_scan_propagates_audit_failure(tmp_path: Path, audit_status: int) -> None:
    result = _run_dependency_scan(tmp_path, audit_status)

    assert result.returncode == audit_status


def test_dependency_scan_accepts_a_clean_audit(tmp_path: Path) -> None:
    result = _run_dependency_scan(tmp_path, 0)

    assert result.returncode == 0, result.stderr


def test_dependency_scan_has_one_declared_canonical_command() -> None:
    manifest = tomllib.loads((REPO_ROOT / "pixi.toml").read_text())
    dev_dependencies = manifest["feature"]["dev"]["pypi-dependencies"]
    runner = CI_RUNNER.read_text()

    assert "pip-audit" in dev_dependencies
    assert runner.count("pixi run pip-audit") == 1
    assert "python -m pip_audit" not in runner
    assert "pip-audit 2>/dev/null" not in runner
    assert "pixi run pip-audit 2>/dev/null || true" not in runner


def test_dependency_audit_is_locked_for_every_supported_platform() -> None:
    lock = yaml.safe_load((REPO_ROOT / "pixi.lock").read_text())
    supported = {platform["name"] for platform in lock["platforms"]}
    resolved = lock["environments"]["default"]["packages"]

    assert set(resolved) == supported
    for platform in supported:
        pypi_artifacts = [
            package["pypi"]
            for package in resolved[platform]
            if isinstance(package, dict) and "pypi" in package
        ]
        assert any("/pip_audit-2.10.1-" in artifact for artifact in pypi_artifacts)
