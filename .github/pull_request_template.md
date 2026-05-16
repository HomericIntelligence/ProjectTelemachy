## Summary

<!-- What does this PR do? Why? One or two sentences. -->

## Related issues

<!-- Closes #N / Refs #N. List one per line. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change (workflow YAML, CLI, or `telemachy.*` public API)
- [ ] Documentation only
- [ ] CI / tooling

## Reviewers, labels, milestone

<!--
Suggested reviewer(s):  @
Suggested label(s):      bug | enhancement | docs | chore | breaking-change
Suggested milestone:     v0.x.y  (see docs/ROADMAP.md if present)

These are hints for the PR author; the actual assignment is done via
the GitHub UI sidebar after the PR is opened.
-->

## Test plan

- [ ] Tests pass (`just test`).
- [ ] Linting passes (`just lint`).
- [ ] Tested locally with `just validate workflows/example.yaml`.
- [ ] New conditional branches have new tests (see `docs/definition-of-done.md`).
- [ ] `CHANGELOG.md` `Unreleased` entry added if user-visible.

## Risk and rollout

- Backwards compatible: yes / no
- Requires schema bump (`apiVersion`): yes / no
- Requires CI / branch-protection changes: yes / no
