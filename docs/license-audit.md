# Dependency License Compatibility Audit

ProjectTelemachy is distributed under the BSD 3-Clause License
(see `LICENSE`). This document records the formal license audit of
runtime dependencies to confirm distribution compatibility.

## Audit date

2026-05-16 (initial)
2026-06-04 (added issue #163 observability packages)

## Method

1. Enumerate runtime dependencies from `pixi.toml`
   `[pypi-dependencies]` (the authoritative declaration; `pyproject.toml`
   carries no runtime `dependencies` table — see `pyproject.toml:5-11`).
2. Resolve each dependency's declared license from its PyPI metadata.
3. Compare each license against the BSD-3-Clause distribution model —
   permissive licenses (MIT, BSD, ISC, Apache 2.0) are compatible;
   weakly-copyleft (LGPL) requires dynamic linking only;
   strong-copyleft (GPL, AGPL) is incompatible.

## Findings

| Dependency | License | Compatible with BSD-3-Clause distribution? |
| --- | --- | --- |
| `pydantic` | MIT | yes |
| `pydantic-settings` | MIT | yes |
| `httpx` | BSD-3-Clause | yes |
| `pyyaml` | MIT | yes |
| `rich` | MIT | yes |
| `typer` | MIT | yes |
| `prometheus-client` | Apache-2.0 | yes |
| `opentelemetry-api` | Apache-2.0 | yes |
| `opentelemetry-sdk` | Apache-2.0 | yes |
| `opentelemetry-instrumentation-httpx` | Apache-2.0 | yes |
| `mcp` | MIT | yes |

All declared runtime dependencies are permissively licensed and
compatible with redistribution under BSD-3-Clause.

## Notes

- `nats-py` (Apache-2.0) was previously declared but has been removed
  from `pixi.toml`; it will be re-added when the NATS subscriber lands
  under #92, at which point this audit must be re-run and the row
  restored.
- Apache-2.0 dependencies, when present, retain their attribution
  requirements; any redistribution of ProjectTelemachy source or
  binaries must preserve the upstream `LICENSE` and `NOTICE` files
  for those dependencies. Standard pip-installed dependencies are
  not redistributed by us; they remain on PyPI under their own terms.
- Development-only dependencies (`pytest`, `pytest-asyncio`,
  `pytest-cov`, `ruff`, `mypy`, `types-PyYAML`, `yamllint`) are not
  audited here because they do not ship in the runtime artifact.

## Re-audit cadence

This audit is re-run:

1. When a runtime dependency is added (including re-adding `nats-py`
   under #92).
2. When a runtime dependency's major version is bumped.
3. Annually if neither of the above has occurred.

To re-verify mechanically, run `pixi run license-audit`, which
prints the current `[pypi-dependencies]` table for comparison
against the Findings section above.

## See also

- `LICENSE`
- `pixi.toml` `[pypi-dependencies]`
- `CONTRIBUTING.md` — runtime-dependency change checklist
- `docs/backwards-compat.md` — separately governs API compatibility
