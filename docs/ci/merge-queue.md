# Merge queue rollout

Telemachy's `main` branch is prepared for a staged GitHub merge-queue rollout.
An independent human must review the workflow changes before the readiness pull
request may merge; following this runbook does not satisfy that review gate. The
queue must not be activated until the readiness pull request has merged, strict
review findings are resolved, and a representative smoke-check pull request is
ready.

The repository-level `homeric-main-baseline` ruleset remains the source of truth
for branch protection. Activation must append one `merge_queue` rule to that
ruleset without changing its conditions, bypass actors, enforcement mode, or
existing rules.

## Required checks

[`configs/github/merge-queue-policy.json`](../../configs/github/merge-queue-policy.json)
is the machine-readable source of truth for the required contexts and approved
queue rule. Inspect the exact context list with:

```bash
jq -r '.required_contexts[]' configs/github/merge-queue-policy.json
```

`.github/workflows/_required.yml` emits these contexts for `push`,
`pull_request`, and `merge_group` `checks_requested` events. The tag-only
`.github/workflows/release.yml` publisher must remain tag-only; it must never run
for merge groups.

## Approved policy

The rule appended during activation must match the artifact's
`merge_queue_rule` object exactly:

```bash
jq '.merge_queue_rule' configs/github/merge-queue-policy.json
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
POLICY=configs/github/merge-queue-policy.json
RULESET_NAME=homeric-main-baseline
RULESET_ID="$(gh api "repos/${REPO}/rulesets" \
  --jq ".[] | select(.name == \"${RULESET_NAME}\") | .id")"
test -n "${RULESET_ID}"

gh api "repos/${REPO}/rulesets/${RULESET_ID}" \
  | jq '{name, target, enforcement, bypass_actors, conditions, rules}' \
  > /tmp/telemachy-ruleset-before.json

jq -e '[.rules[] | select(.type == "merge_queue")] | length == 0' \
  /tmp/telemachy-ruleset-before.json

jq --slurpfile policy "${POLICY}" -e '
  ([.rules[] | select(.type == "required_status_checks")
    | .parameters.required_status_checks[].context] | sort)
  == ($policy[0].required_contexts | sort)
' /tmp/telemachy-ruleset-before.json

jq --slurpfile policy "${POLICY}" \
  '.rules += [$policy[0].merge_queue_rule]' \
  /tmp/telemachy-ruleset-before.json \
  > /tmp/telemachy-ruleset-with-queue.json

gh api --method PUT "repos/${REPO}/rulesets/${RULESET_ID}" \
  --input /tmp/telemachy-ruleset-with-queue.json
```

After the update, verify the live policy and run the smoke check:

```bash
gh api "repos/${REPO}/rulesets/${RULESET_ID}" \
  | jq --slurpfile policy "${POLICY}" -e '
      [.rules[] | select(.type == "merge_queue")]
      == [$policy[0].merge_queue_rule]
    '

SMOKE_PR=123  # Replace with the designated smoke pull request number.
OWNER="${REPO%%/*}"
NAME="${REPO#*/}"
REQUESTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PR_HEAD_SHA="$(gh pr view "${SMOKE_PR}" --repo "${REPO}" \
  --json headRefOid --jq '.headRefOid')"
test -n "${PR_HEAD_SHA}"
printf 'smoke_pr=%s requested_at=%s pr_head_sha=%s\n' \
  "${SMOKE_PR}" "${REQUESTED_AT}" "${PR_HEAD_SHA}"

gh pr merge --auto --squash "${SMOKE_PR}" --repo "${REPO}"

# Poll the designated PR until GitHub records its actual queue entry. The entry
# provides both the authoritative enqueue time and that entry's queue head SHA.
QUEUE_ENTRY=""
for attempt in {1..60}; do
  QUEUE_ENTRY="$(gh api graphql \
    -f owner="${OWNER}" -f name="${NAME}" -F number="${SMOKE_PR}" \
    -f query='
      query($owner: String!, $name: String!, $number: Int!) {
        repository(owner: $owner, name: $name) {
          pullRequest(number: $number) {
            mergeQueueEntry {
              enqueuedAt
              headCommit { oid }
            }
          }
        }
      }
    ' --jq '
      .data.repository.pullRequest.mergeQueueEntry
      | select(. != null and .headCommit != null)
      | {enqueuedAt, queueHeadSha: .headCommit.oid}
    ')"
  [[ -n "${QUEUE_ENTRY}" ]] && break
  sleep 10
done
test -n "${QUEUE_ENTRY}"

ENQUEUED_AT="$(jq -r '.enqueuedAt' <<<"${QUEUE_ENTRY}")"
QUEUE_HEAD_SHA="$(jq -r '.queueHeadSha' <<<"${QUEUE_ENTRY}")"
CURRENT_PR_HEAD_SHA="$(gh pr view "${SMOKE_PR}" --repo "${REPO}" \
  --json headRefOid --jq '.headRefOid')"
[[ "${CURRENT_PR_HEAD_SHA}" == "${PR_HEAD_SHA}" ]]
printf 'smoke_pr=%s enqueued_at=%s pr_head_sha=%s queue_head_sha=%s\n' \
  "${SMOKE_PR}" "${ENQUEUED_AT}" "${PR_HEAD_SHA}" "${QUEUE_HEAD_SHA}"

# Select only a newly-created merge_group run for this exact queue head. Do not
# use the repository's latest merge-group run: it may belong to a different PR.
RUN_JSON=""
for attempt in {1..60}; do
  RUN_JSON="$(gh api --method GET \
    "repos/${REPO}/actions/workflows/_required.yml/runs" \
    -f event=merge_group \
    -f head_sha="${QUEUE_HEAD_SHA}" \
    -f created=">=${ENQUEUED_AT}" \
    -f per_page=100 \
    | jq -c --arg queue_head_sha "${QUEUE_HEAD_SHA}" \
      --arg enqueued_at "${ENQUEUED_AT}" '
        [.workflow_runs[]
         | select(
             .event == "merge_group"
             and .head_sha == $queue_head_sha
             and .created_at >= $enqueued_at
           )]
        | sort_by(.created_at)
        | first // empty
      ')"
  [[ -n "${RUN_JSON}" ]] && break
  sleep 10
done
test -n "${RUN_JSON}"

RUN_ID="$(jq -r '.id' <<<"${RUN_JSON}")"
gh run watch "${RUN_ID}" --repo "${REPO}" --exit-status

RUN_JSON="$(gh api "repos/${REPO}/actions/runs/${RUN_ID}")"
jq -e --arg queue_head_sha "${QUEUE_HEAD_SHA}" \
  --arg enqueued_at "${ENQUEUED_AT}" '
    .event == "merge_group"
    and .head_sha == $queue_head_sha
    and .created_at >= $enqueued_at
    and .status == "completed"
    and .conclusion == "success"
  ' <<<"${RUN_JSON}"
jq '{id,event,head_sha,created_at,status,conclusion,html_url}' \
  <<<"${RUN_JSON}"

EXPECTED="$(jq -c '.required_contexts | sort' "${POLICY}")"
JOBS_JSON="$(mktemp)"
CHECK_RUNS_JSON="$(mktemp)"
trap 'rm -f "${JOBS_JSON}" "${CHECK_RUNS_JSON}"' EXIT

gh api --paginate \
  "repos/${REPO}/actions/runs/${RUN_ID}/jobs?per_page=100" \
  --jq '.jobs[]' | jq -s '.' > "${JOBS_JSON}"

JOB_NAMES="$(jq -c --argjson expected "${EXPECTED}" '
  [.[]
   | select(.name as $name | $expected | index($name))
   | .name]
  | sort
' "${JOBS_JSON}")"
[[ "${JOB_NAMES}" == "${EXPECTED}" ]]

jq -e --argjson expected "${EXPECTED}" \
  --arg queue_head_sha "${QUEUE_HEAD_SHA}" '
    [.[] | select(.name as $name | $expected | index($name))]
    | all(.[];
        .head_sha == $queue_head_sha
        and .status == "completed"
        and .conclusion == "success"
      )
  ' "${JOBS_JSON}"

while IFS= read -r check_run_url; do
  gh api "repos/${REPO}/check-runs/${check_run_url##*/}"
done < <(jq -r --argjson expected "${EXPECTED}" '
  .[]
  | select(.name as $name | $expected | index($name))
  | .check_run_url
' "${JOBS_JSON}") | jq -s '.' > "${CHECK_RUNS_JSON}"

CHECK_RUN_NAMES="$(jq -c '[.[].name] | sort' "${CHECK_RUNS_JSON}")"
[[ "${CHECK_RUN_NAMES}" == "${EXPECTED}" ]]

jq -e --arg queue_head_sha "${QUEUE_HEAD_SHA}" '
  all(.[];
    .head_sha == $queue_head_sha
    and .status == "completed"
    and .conclusion == "success"
  )
' "${CHECK_RUNS_JSON}"
```

The selected run is tied to the designated smoke pull request through its merge
queue entry, actual enqueue time, and exact queue head SHA. The job query then
follows that run's `check_run_url` values. Both the required job names and their
check-run names must equal the 12-context artifact exactly, without missing or
duplicate required contexts, and every required job and check run must finish
successfully. Additional advisory jobs may run but are not policy contexts.

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
