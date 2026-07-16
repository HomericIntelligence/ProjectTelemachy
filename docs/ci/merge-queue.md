# Merge queue rollout

Telemachy's `main` branch is prepared for a staged GitHub merge-queue rollout.
The queue must not be activated until the readiness pull request has merged,
strict review has passed, and a representative smoke-check pull request is ready.

The repository-level `homeric-main-baseline` ruleset remains the source of truth
for branch protection. Activation must append one `merge_queue` rule to that
ruleset without changing its conditions, bypass actors, enforcement mode, or
existing rules.

## Required checks

The queue must preserve all required GitHub Actions contexts:

- `lint`
- `unit-tests`
- `integration-tests`
- `security/dependency-scan`
- `security/secrets-scan`
- `build`
- `schema-validation`
- `deps/version-sync`
- `test`
- `package`
- `install`
- `release`

`.github/workflows/_required.yml` emits these contexts for `push`,
`pull_request`, and `merge_group` `checks_requested` events. The tag-only
`.github/workflows/release.yml` publisher must remain tag-only; it must never run
for merge groups.

## Approved policy

The rule appended during activation must match this object exactly.

<!-- merge-queue-rule -->
```json
{
  "type": "merge_queue",
  "parameters": {
    "check_response_timeout_minutes": 60,
    "grouping_strategy": "ALLGREEN",
    "max_entries_to_build": 10,
    "max_entries_to_merge": 5,
    "merge_method": "SQUASH",
    "min_entries_to_merge": 1,
    "min_entries_to_merge_wait_minutes": 5
  }
}
```

This means at most 10 queue entries may request builds concurrently, at most 5
entries may merge as a group, and a group may proceed with one entry after the
5-minute wait. Required checks have 60 minutes to report. `ALLGREEN` requires
every pull request represented in the group to satisfy the required checks.

## Post-merge activation

Activation is an operator step, not part of the readiness pull request.

1. Confirm the readiness change is on `main` and its required checks are green.
2. Confirm a representative pull request is ready to enter the queue.
3. Re-read the live ruleset and save a restorable payload.
4. Append only the approved `merge_queue` rule and update the full ruleset.
5. Re-read the ruleset, then queue the smoke pull request with squash.
6. Confirm a `merge_group` run emits and passes all required contexts before the
   pull request merges.
7. Record the ruleset response, workflow run, and queued merge in issue #308.

The following commands preserve the full live ruleset and refuse to append a
second queue rule. Review both generated JSON files before running the `PUT`.

```bash
REPO=HomericIntelligence/Telemachy
RULESET_NAME=homeric-main-baseline
RULESET_ID="$(gh api "repos/${REPO}/rulesets" \
  --jq ".[] | select(.name == \"${RULESET_NAME}\") | .id")"
test -n "${RULESET_ID}"

gh api "repos/${REPO}/rulesets/${RULESET_ID}" \
  | jq '{name, target, enforcement, bypass_actors, conditions, rules}' \
  > /tmp/telemachy-ruleset-before.json

jq -e '[.rules[] | select(.type == "merge_queue")] | length == 0' \
  /tmp/telemachy-ruleset-before.json

jq '.rules += [{
  "type": "merge_queue",
  "parameters": {
    "check_response_timeout_minutes": 60,
    "grouping_strategy": "ALLGREEN",
    "max_entries_to_build": 10,
    "max_entries_to_merge": 5,
    "merge_method": "SQUASH",
    "min_entries_to_merge": 1,
    "min_entries_to_merge_wait_minutes": 5
  }
}]' /tmp/telemachy-ruleset-before.json \
  > /tmp/telemachy-ruleset-with-queue.json

gh api --method PUT "repos/${REPO}/rulesets/${RULESET_ID}" \
  --input /tmp/telemachy-ruleset-with-queue.json
```

After the update, verify the live policy and run the smoke check:

```bash
gh api "repos/${REPO}/rulesets/${RULESET_ID}" \
  --jq '.rules[] | select(.type == "merge_queue")'

gh pr merge --auto --squash <SMOKE-PR> --repo "${REPO}"
gh run list --repo "${REPO}" --workflow _required.yml --event merge_group \
  --limit 1 --json databaseId,event,headSha,status,conclusion,url
```

Do not remove or rename any required context during activation. The queue rule
does not carry a separate check list; it relies on the existing
`required_status_checks` rule in the same ruleset.

## Rollback

If the rule update does not preserve the ruleset or the smoke check cannot emit
all required contexts, stop the rollout and restore the reviewed snapshot:

```bash
gh api --method PUT "repos/${REPO}/rulesets/${RULESET_ID}" \
  --input /tmp/telemachy-ruleset-before.json
```

Re-read the ruleset after rollback and confirm the `merge_queue` rule is absent
while all pre-existing required contexts and protection rules remain intact.
