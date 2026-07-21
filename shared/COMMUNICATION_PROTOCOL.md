# Communication Protocol

## Workspace: `.on-loop/`

The workflow directs inter-agent communication through the `.on-loop/` directory in the project root. Each `/on-loop` invocation creates a **session** under `.on-loop/sessions/` intended to be committed as an editable operational record, not an immutable or mechanically complete audit log.

## Session Directory Naming

Session directories are named `YYYYMMDD_HHMMSS_<branch-slug>` for human readability and chronological sorting:

```
.on-loop/sessions/20260426_143052_user-management-api/
.on-loop/sessions/20260426_150311_auth-middleware/
```

Each session also has a UUID (`session_id`) for lock coordination, but the **directory name** is the human-readable session name.

## Session Directory Structure

```
.on-loop/
├── index.json                      # Session manifest (all sessions)
└── sessions/
    ├── 20260426_143052_user-management-api/
    │   ├── state.json              # Phase tracking (orchestrator-only writes)
    │   ├── plan.md                 # Implementation plan (all agents read)
    │   ├── changes.log             # Append-only file modification log
    │   └── agent-notes/
    │       ├── architect.md        # Architect agent output
    │       ├── coding.md           # Coding agent output
    │       ├── testing.md          # Testing agent output
    │       ├── security.md         # Security agent output
    │       ├── documentation.md    # Documentation agent output
    │       ├── build.md            # Build agent output
    │       └── reviewer.md         # Reviewer agent output
    └── 20260426_150311_auth-middleware/
        └── ...
```

## Worktree Isolation

Each session operates in a **git worktree** at `.claude/worktrees/<branch-slug>/`. This isolates checked-out feature files between sessions and from the user's working directory. Shared session and roadmap metadata are still ordinary files without atomic cross-process coordination; see [`commands/on-continue.md`](../commands/on-continue.md) for the concurrency limitation.

```
.claude/worktrees/                  # gitignored, temporary
├── <branch-slug-1>/               # worktree for session 1
└── <branch-slug-2>/               # worktree for session 2
```

- Agents read/write **feature code** in the worktree
- Agents read/write **session state** in the original repo root (`.on-loop/sessions/<id>/`)
- `/on-loop` and `/on-loop-continue` retain worktrees on COMPLETE and FAILED for continuation, inspection, or resume
- `/on-loop:clear` is the explicit removal path and never merges PRs

## index.json Schema

```json
{
  "version": "1.0",
  "sessions": [
    {
      "session_id": "<uuid>",
      "session_name": "<YYYYMMDD_HHMMSS_branch-slug>",
      "loop_id": "<uuid>",
      "prompt": "<first 100 chars of prompt>",
      "branch": "<branch name>",
      "status": "active | complete | failed",
      "started_at": "<ISO 8601>",
      "completed_at": "<ISO 8601 or null>",
      "worktree_path": ".claude/worktrees/<branch-slug>",
      "session_dir": ".on-loop/sessions/<session-name>",
      "pr_url": null
    }
  ]
}
```

## state.json Schema (v1.1)

```json
{
  "version": "1.1",
  "loop_id": "<uuid>",
  "session_id": "<uuid>",
  "prompt": "<original user prompt>",
  "phase": "INIT | SPEC | PLAN | CODE | TEST | SECURITY | DOC | BUILD | REVIEW | GIT | COMPLETE | FAILED",
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
  "current_agent": "<agent name>",
  "error": null,
  "todos": [],
  "waivers": []
}
```

### Rules

- **Only the orchestrator writes `state.json`**. All other agents read it.
- Phase transitions must follow the valid sequence (see `skills/loop-state/SKILL.md`).
- When a TEST, SECURITY, or REVIEW retry limit is exhausted, the orchestrator records unresolved issues, sets the session to `FAILED`, and stops. It advances only after an explicit human waiver is recorded in `state.json.waivers` and `changes.log` as specified by `skills/quality-gate/SKILL.md`.

## plan.md Format

Written by the orchestrator after the SPEC phase. All agents reference this.

```markdown
# Implementation Plan

## Objective
<one-line summary>

## Spec Reference
<key decisions from architect's spec>

## Tasks
1. <task> — assigned to <agent>
2. <task> — assigned to <agent>
...

## Constraints
- <constraint from spec>

## Open Questions
- <question> — owner: <agent>
```

## changes.log Format

Append-only. Every agent appends when it creates, modifies, or deletes a file.

```
[<ISO 8601>] <agent> <action> <file_path> — <reason>
```

Example:
```
[2026-03-21T10:15:00Z] coding CREATE src/api/handler.ts — implement POST /users endpoint
[2026-03-21T10:16:30Z] coding MODIFY src/api/handler.ts — add input validation
[2026-03-21T10:20:00Z] testing CREATE tests/api/handler.test.ts — unit tests for POST /users
```

File paths in `changes.log` are relative to the **worktree root**.

## Agent Notes Format

Each agent writes structured notes to `<session-dir>/agent-notes/<agent>.md`:

```markdown
# <Agent Name> Notes

## Summary
<2-3 sentence summary of what was done>

## Decisions
- <decision made and rationale>

## Files Modified
- `<path>` — <what changed>

## Issues Found
- [SEVERITY] <description> — <recommendation>

## Recommendations for Next Agent
- <actionable recommendation>
```

### Severity Levels (for Issues)

| Level | Meaning |
|-------|---------|
| CRITICAL | Must fix before merge; security vulnerability or data loss risk |
| HIGH | Should fix before merge; significant correctness or reliability issue |
| MEDIUM | Fix soon; code quality, performance, or maintainability concern |
| LOW | Nice to have; style, naming, minor improvements |
| INFO | Observation; no action required |

## Rules for All Agents

1. **Read before write** — Always read `state.json` and `plan.md` from the session directory before starting work
2. **Append to changes.log** — Log every file operation (paths relative to worktree root)
3. **Write agent notes** — Always write structured notes when your phase completes
4. **Respect boundaries** — Only perform actions within your agent's responsibility
5. **Work in the worktree** — All file reads/writes for feature code happen in the worktree directory
6. **Flag blockers** — If you cannot proceed, document the blocker in your agent notes and set an issue with CRITICAL severity
7. **No direct agent-to-agent communication** — All information flows through session directory files
