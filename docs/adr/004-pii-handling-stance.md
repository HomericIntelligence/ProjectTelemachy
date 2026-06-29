# ADR-004: PII handling stance for workflow text

- **Status:** Accepted
- **Date:** 2026-06-03
- **Deciders:** mvillmow
- **Context tags:** privacy, logging, schema

## Context

Workflow YAML files contain free-text `subject` and `description` fields.
There is no schema constraint, validator, or runtime redaction. The text is
transmitted to ProjectAgamemnon (`agamemnon_client.py:228-231`) and the
`subject` is emitted to the `telemachy` logger at INFO (`executor.py:307`).
Issue #186 flagged the absence of any GDPR / privacy guidance.

## Decision

1. Telemachy treats workflow text as opaque application data and forwards
   it to Agamemnon verbatim. Rewriting `description` on the wire would
   silently break workflows.
2. Telemachy does NOT ship an in-tree PII redaction filter. A heuristic
   regex over log messages would have false-positive redactions on
   legitimate content (model names like `claude-opus-4-8`, agent names,
   typical task subjects), giving operators a false sense of guarantee.
   Operators that need redaction should apply it at their log-shipping
   layer where it can be tuned to their actual log format.
3. We document the data flow, author guidance, and operator levers in
   `docs/privacy.md` and link it from `SECURITY.md`, `README.md`,
   `CLAUDE.md`, and the example workflow YAMLs.
4. We do NOT add a `contains_pii` schema field. Doing so would be a MINOR
   public-API bump per `docs/backwards-compat.md` and would not actually
   block personal data from being submitted.

## Consequences

- Operators get an explicit, documented data-handling story they can take
  to a privacy review.
- No new env vars, no new code, no schema change, no behavior change.
- Operators retain responsibility for choosing a log-redaction approach
  (shipping-side scrubber, `LOG_LEVEL=WARNING`, etc.).
- The privacy table in `docs/privacy.md` must be revisited when issue
  #92's NATS subscriber lands, since that may introduce new sinks.

## Alternatives considered

- **Ship an in-tree opt-in `LOG_REDACT_PII` filter.** Rejected — the only
  workable heuristic (long-alnum-run redaction) routinely matches model
  names, agent names, and task subjects, producing degraded log output
  for operators who enable it. False sense of guarantee for a feature
  the issue did not request.
- **Add `contains_pii: bool` to `TaskSpec` and refuse to log when true.**
  Rejected — would not prevent PII transmission to Agamemnon, forces a
  MINOR version bump, and places enforcement on workflow authors.
- **Rewrite `description` on the wire.** Rejected — breaks Agamemnon-side
  task execution.

## References

- Issue #186
- Epic #92
- `docs/privacy.md`
- `docs/backwards-compat.md`
