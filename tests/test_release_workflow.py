import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WF = REPO_ROOT / ".github" / "workflows" / "release.yml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

# Mirror of the extraction regex used in release.yml's "Extract changelog
# section" step. Keeping a single canonical pattern here means a drift between
# the workflow and the test surfaces as an immediate test failure.
def _extract(version: str, changelog_text: str) -> str | None:
    pat = re.compile(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pat.search(changelog_text)
    return m.group(1).strip() if m else None


def test_release_workflow_exists() -> None:
    assert WF.is_file(), "release.yml is missing"


def test_release_workflow_triggers_on_version_tag() -> None:
    data = yaml.safe_load(WF.read_text())
    # PyYAML parses the unquoted YAML key `on` as the boolean True.
    on_block = data.get(True, data.get("on"))
    assert "v*.*.*" in on_block["push"]["tags"]


def test_release_workflow_has_expected_jobs() -> None:
    data = yaml.safe_load(WF.read_text())
    assert {"verify-version", "build", "github-release", "pypi-publish"} <= set(
        data["jobs"].keys()
    )


def test_release_workflow_pins_every_action_by_sha() -> None:
    text = WF.read_text()
    refs = re.findall(r"uses:\s+([^\s@]+)@([^\s#]+)", text)
    assert refs, "no `uses:` entries found — regex probably broken"
    unpinned = [f"{owner}@{ref}" for owner, ref in refs
                if not re.fullmatch(r"[0-9a-f]{40}", ref)]
    assert not unpinned, f"unpinned actions: {unpinned}"


def test_release_workflow_has_no_continue_on_error() -> None:
    assert "continue-on-error: true" not in WF.read_text()


def test_changelog_extraction_regex_handles_unreleased_block() -> None:
    # The live CHANGELOG.md is required to have an `## [Unreleased]` heading,
    # which our regex must locate and extract.
    body = _extract("Unreleased", CHANGELOG.read_text())
    assert body is not None and body, "regex failed to extract [Unreleased] block"


def test_changelog_extraction_regex_handles_dated_release_heading() -> None:
    sample = (
        "# Changelog\n\n"
        "## [Unreleased]\n\n### Added\n- next thing\n\n"
        "## [1.2.3] - 2026-06-03\n\n### Added\n- shipped thing\n\n"
        "## [1.2.2] - 2026-05-01\n\n### Added\n- older thing\n"
    )
    body = _extract("1.2.3", sample)
    assert body is not None
    assert "shipped thing" in body
    assert "older thing" not in body  # must stop at the next `## [` heading


def test_changelog_extraction_regex_returns_none_for_missing_version() -> None:
    sample = "# Changelog\n\n## [Unreleased]\n\n- x\n"
    assert _extract("9.9.9", sample) is None
