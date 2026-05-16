# Dependency License Compatibility Audit

ProjectTelemachy is distributed under the MIT License (see `LICENSE`).
This document records the formal license audit of runtime dependencies
to confirm distribution compatibility.

## Audit date

2026-05-16

## Method

1. Enumerate runtime dependencies from `pyproject.toml` and `pixi.toml`
   `[pypi-dependencies]`.
2. Resolve each dependency's declared license from its PyPI metadata
   and source distribution.
3. Compare each license against the MIT distribution model — any
   permissive license (MIT, BSD, ISC, Apache 2.0) is compatible;
   weakly-copyleft licenses (LGPL) require dynamic linking only;
   strong-copyleft (GPL, AGPL) is incompatible.

## Findings

| Dependency | License | Compatible with MIT distribution? |
|---|---|---|
| `httpx` | BSD-3-Clause | yes |
| `pydantic` | MIT | yes |
| `pydantic-settings` | MIT | yes |
| `typer` | MIT | yes |
| `rich` | MIT | yes |
| `pyyaml` | MIT | yes |
| `nats-py` | Apache-2.0 | yes |

All declared runtime dependencies are permissively licensed and
compatible with redistribution under MIT.

## Notes

- `nats-py` is currently declared but unused in code (see issues
  #154 / #196). Once removed it can be dropped from this table.
- Apache-2.0 dependencies retain their attribution requirements; any
  redistribution of ProjectTelemachy source or binaries must preserve
  the upstream `LICENSE` and `NOTICE` files for those dependencies.
  (Standard pip-installed dependencies are not redistributed by us;
  they remain on PyPI under their own terms.)
- Development-only dependencies (`pytest`, `ruff`, `pre-commit`) are
  not audited here because they do not ship in the runtime artifact.

## Re-audit cadence

This audit is re-run:

1. When a runtime dependency is added.
2. When a runtime dependency's major version is bumped.
3. Annually if neither of the above has occurred.

## See also

- `LICENSE`
- `pyproject.toml` `[project] dependencies`
- `docs/backwards-compat.md` — separately governs API compatibility
