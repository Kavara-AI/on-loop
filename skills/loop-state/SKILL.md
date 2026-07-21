---
name: loop-state
description: Manages on-loop phase state transitions, validation, and persistence
---

# Loop State Management

This skill manages the session `state.json` lifecycle — creation, valid transitions, and persistence. Each session's state lives at `.on-loop/sessions/<session-name>/state.json` where `<session-name>` is `YYYYMMDD_HHMMSS_<branch-slug>` (e.g., `20260426_143052_user-management-api`).

## Valid Phase Transitions

```
INIT → SPEC
SPEC → PLAN
PLAN → CODE
CODE → TEST
TEST → CODE          (retry: test failures)
TEST → SECURITY      (pass)
SECURITY → CODE      (retry: security blockers)
SECURITY → DOC       (pass, parallel with BUILD)
SECURITY → BUILD     (pass, parallel with DOC)
DOC → REVIEW         (when BUILD also complete)
BUILD → REVIEW       (when DOC also complete)
REVIEW → CODE        (retry: changes requested)
REVIEW → GIT         (approved)
GIT → COMPLETE       (commit, push, PR done)
ANY → FAILED         (unrecoverable error)
FAILED → ANY         (resume)
```

## State Operations

### Initialize State

```json
{
  "version": "1.1",
  "loop_id": "<uuid>",
  "session_id": "<uuid>",
  "prompt": "<user prompt>",
  "phase": "INIT",
  "started_at": "<ISO 8601>",
  "updated_at": "<ISO 8601>",
  "retries": {
    "test_to_code": 0,
    "security_to_code": 0,
    "review_to_code": 0
  },
  "max_retries": {
    "test_to_code": 3,
    "security_to_code": 2,
    "review_to_code": 2
  },
  "branch": null,
  "worktree_path": ".claude/worktrees/<branch-slug>",
  "session_dir": ".on-loop/sessions/<session-name>",
  "pr_url": null,
  "phases_completed": [],
  "current_agent": "orchestrator",
  "error": null,
  "todos": [],
  "waivers": []
}
```

New fields in v1.1:
- `session_id`: UUID v4 identifying this session (same as the session directory name)
- `worktree_path`: Relative path to the git worktree for this session
- `session_dir`: Relative path to the session log directory under `.on-loop/sessions/`

### Transition Phase

When transitioning:
1. Validate the transition is allowed (see valid transitions above)
2. Add the current phase to `phases_completed` (if not already there)
3. Update `phase` to the new phase
4. Update `updated_at` to current timestamp
5. Update `current_agent` to the agent for the new phase
6. Write `state.json`

### Record Retry

When a retry is triggered:
1. Increment the appropriate retry counter
2. Check if the counter exceeds the maximum
3. If within limit: transition back to CODE
4. If exhausted: record the unresolved issues, transition to `FAILED`, set `error` to `retry_exhausted:<phase>`, and stop pending an explicit human waiver

### Record TODO

When a retry limit is exhausted:
```json
{
  "phase": "<phase that failed>",
  "description": "<what wasn't resolved>",
  "severity": "<CRITICAL|HIGH|MEDIUM|LOW>",
  "details": "<specific issues>"
}
```

### Record Human Waiver

Retry exhaustion is fail-closed. A generic resume request is not approval. After showing all unresolved issues, require an explicit human statement identifying what is accepted and directing the workflow to proceed. Append the phase, accepted issue list, exact statement, and timestamp to `waivers`; append a `HUMAN_WAIVER` entry to `changes.log`; then clear the error and transition to the phase following the waived gate. Never infer or manufacture a waiver. See `skills/quality-gate/SKILL.md` for the record format.

### Record Error

When an unrecoverable error occurs:
1. Set `phase` to `"FAILED"`
2. Set `error` to a description of what went wrong
3. Set `updated_at`
4. The loop can be resumed with `/on-loop-resume`; retry exhaustion remains stopped until its waiver is explicitly recorded

## Phase to Agent Mapping

| Phase | Agent | Notes |
|-------|-------|-------|
| INIT | orchestrator | Workspace setup |
| SPEC | architect | Spec generation |
| PLAN | orchestrator | Plan from spec |
| CODE | coding | Implementation or remediation |
| TEST | testing | Test generation and execution |
| SECURITY | security | Security audit (read-only) |
| DOC | documentation | Documentation generation |
| BUILD | build | Build infrastructure |
| REVIEW | reviewer | Final review gate (read-only) |
| GIT | orchestrator | Commit, push, create PR |
| COMPLETE | orchestrator | Summary; retain worktree for continuation or inspection |

## Rules

1. Only the orchestrator agent writes `state.json`
2. All other agents read `state.json` to understand context
3. Phase transitions must follow the valid transition graph
4. Retry counters persist across transitions (never reset mid-loop)
5. TODOs and waivers are append-only during a loop run
6. The `version` field enables future schema migrations
