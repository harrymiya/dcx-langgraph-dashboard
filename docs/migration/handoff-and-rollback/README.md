# Agent Handoff, Status, and Rollback Contract

GOV-04 owns this directory only. DAG tasks split implementation work and express dependencies. Do not add a per-task human-review gate; people retest and accept after task closure.

## Status and ownership

- `planned`: eligible for claim when dependencies and retry time permit.
- `in-progress`: one worker owns a time-bounded lease. Record `owner`, `claimed_at`, `lease_expires_at`, `status_source`, and increment `autonomous_attempt`.
- `blocked`: execution failed or cannot proceed. Record `last_error`, `last_report`, `last_checks`, `autonomous_failure`, and `retry_after`; release the lease. A retry must create a new attempt and preserve the prior failure evidence.
- `code-ready`: development task closed after implementation and directly relevant automated tests pass. Human retesting and acceptance happen later. A concise summary and the test result are enough; no extra evidence package is required.
- `contract-ready`, `release-ready`: retain for existing specialized workflows, but ordinary implementation tasks close as `code-ready`.

Claiming and completion must be based on the latest task snapshot. A worker may heartbeat, complete, block, or release only its own active lease. Expired leases may be reclaimed. Never infer completion from a merge or a Markdown narrative.

## Machine result record

```json
{
  "worker_id": "agent-<stable-id>",
  "summary": "Concise machine-generated outcome",
  "report": "path/to/task-report.md",
  "changed_files": ["owned/path"],
  "limitations": [],
  "checks": [
    {
      "command": "exact command including arguments",
      "exit_code": 0,
      "result": "short machine-readable outcome",
      "artifact": "optional relative artifact path"
    }
  ],
  "verified_at": "ISO-8601 UTC"
}
```

Record the actual relevant test command and result. Do not investigate external evidence or create acceptance artifacts for ordinary tasks. Keep existing authorization requirements for real health data, payments, messages, production deployment, and external writes; never report an unrun check as passing.

## File claims and shared writes

Each task claims the narrowest owned paths before editing. Reject overlapping claims unless the shared-path owner explicitly coordinates the change and the integration protocol permits it. Page tasks submit route fragments only; FND-03 alone writes the central route registry. GOV-04 alone writes this directory. Do not use `git add .`; stage only task-owned paths. Recheck the staged path list before commit. A documentation claim is not a runtime lock: the current state helper does not provide atomic cross-process file locking, so concurrent shared writes still require an external serialized coordinator or must be blocked.

## Block, resume, retry

On a failed relevant check, fix and rerun it. If work cannot continue, mark the task blocked with a concise reason and release the lease. Resume after the dependency and retry gates pass. Do not create a broader failure dossier.

## Task rollback record

Before implementation, name the task-owned change, last known-good revision/artifact, trigger, operator/action, and verification. On failure, stop further writes, disable only the affected flag/entry where applicable, restore the last known-good task-owned files/artifact, and run the relevant checks again. Preserve audit and business facts; do not delete or rewrite authoritative transactions. For uncertain or irreversible state, fail closed and escalate through the owning task rather than attempting an unverified data rollback.

```yaml
rollback:
  trigger: "failed automated check or unsafe behavior"
  owned_paths: ["task-owned/path"]
  last_known_good: "commit or artifact identifier"
  action: "restore owned paths or disable the affected entry"
  verification:
    - command: "exact rollback verification command"
      exit_code: 0
  limitations: []
```

## Scope boundaries

This contract changes no application code, task status, backend task manifest, route registry, credentials, or production state. `planned` remains the design-stage task status until a separately authorized task records its own machine evidence.
